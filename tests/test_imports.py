import io

from openpyxl import Workbook
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.imports import ImportDataRow, ImportJobRow, OzonImportService
from apps.control_plane.sql_repository import Base


def test_ozon_csv_import_is_normalized_and_idempotent():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    service = OzonImportService(engine)
    content = (
        "номер заказа;артикул;количество;валюта;цена;дата заказа\n1001;SKU-1;2;RUB;1 299,50;2026-07-16T10:00:00+03:00\n"
    ).encode()

    first = service.import_file(filename="orders.csv", content=content)
    second = service.import_file(filename="orders.csv", content=content)

    assert first.status == "completed"
    assert first.row_count == 1
    assert first.accepted_count == 1
    assert first.mapping["external_id"] == "номер заказа"
    assert second.id == first.id
    assert second.duplicate is True


def test_ozon_import_reports_missing_required_columns():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    result = OzonImportService(engine).import_file(filename="orders.csv", content=b"foo,bar\na,b\n")

    assert result.status == "rejected"
    assert {"external_id", "sku"}.issubset({item["field"] for item in result.errors})


def test_ozon_import_preview_is_read_only_and_reports_missing_columns():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    service = OzonImportService(engine)

    ready = service.preview_file(
        filename="transactions.csv",
        content=(
            b"operation_id;fee_type;amount;currency;effective_at\n"
            b"op-1;delivery;10;RUB;2025-10-01T10:00:00+03:00\n"
        ),
    )
    blocked = service.preview_file(filename="transactions.csv", content=b"foo,bar\na,b\n")

    assert ready.ready is True
    assert ready.record_type == "ozon_fee"
    assert ready.row_count == 1
    assert blocked.ready is False
    assert {"external_id", "fee_type", "amount", "currency", "effective_at"} == set(
        blocked.missing_columns
    )
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ImportJobRow)) == 0


def test_official_ozon_accrual_xlsx_preserves_all_rows_without_treating_revenue_as_fee():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Начисления"
    sheet.append(["Период: 01.10.2025-31.10.2025"])
    sheet.append(
        [
            "ID начисления",
            "Дата начисления",
            "Группа услуг",
            "Тип начисления",
            "Артикул",
            "SKU",
            "Сумма итого, руб.",
        ]
    )
    sheet.append(["order-1", "2025-10-04T00:00:00+03:00", "Продажи", "Выручка", "offer-1", "sku-1", 6512])
    sheet.append(["order-1", "2025-10-04T00:00:00+03:00", "Продажи", "Программы партнёров", None, None, 0])
    sheet.append([None, "2025-10-15T00:00:00+03:00", "Прочие начисления", "Взаимозачет", None, None, -14698.76])
    content = io.BytesIO()
    workbook.save(content)

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    service = OzonImportService(engine)
    preview = service.preview_file(filename="Отчет по начислениям_01.10.2025-31.10.2025.xlsx", content=content.getvalue())

    assert preview.ready is True
    assert preview.record_type == "ozon_accrual"
    assert preview.row_count == 3
    assert preview.mapping["currency"] == "__derived_rub_from_amount_header__"

    imported = service.import_file(
        filename="Отчет по начислениям_01.10.2025-31.10.2025.xlsx", content=content.getvalue()
    )
    assert imported.status == "completed"
    assert imported.accepted_count == 3
    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(ImportDataRow).where(ImportDataRow.import_id == imported.id).order_by(ImportDataRow.row_number)
            )
        )
    assert rows[0].normalized_json["accrual_type"] == "Выручка"
    assert rows[0].normalized_json["currency"] == "RUB"
    assert rows[1].normalized_json["amount"] == "0"
    assert rows[2].payload_json["ID начисления"] is None
    assert rows[2].normalized_json["external_id"].startswith("report-row:")

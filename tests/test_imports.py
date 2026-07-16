from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.imports import OzonImportService
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

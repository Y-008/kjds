from __future__ import annotations

from pathlib import Path

from scripts.extract_ru002_logistics_evidence import (
    EvidenceHit,
    extract_image_hits,
    extract_legacy_doc,
    extract_xlsx_hits,
    infer_cost_legs,
    render_markdown,
    sanitize_text,
    structured_records,
)

WULIU = Path(__file__).resolve().parents[1] / "wuliu"


def test_xlsx_scan_finds_yandex_fees_and_rub_currency():
    path = WULIU / "【2025.11.26】Yandex产品测费表(1).xlsx"
    hits = extract_xlsx_hits(path, row_limit=12, col_limit=14)
    joined = "\n".join(hit.excerpt for hit in hits)

    assert "703卢布/kg + 158卢布/票" in joined
    assert "538卢布/kg +76卢布/票" in joined
    assert any(hit.currency == "RUB" for hit in hits)
    assert any(hit.location.startswith("Sheet1!") for hit in hits)


def test_image_ocr_sanitizes_contacts_and_keeps_service_fees():
    path = WULIU / "1600858dfc1b43297c8c1fb7526b4a28.jpg"
    hits = extract_image_hits(path)
    joined = "\n".join(hit.excerpt for hit in hits)

    assert "代 贴 单" in joined or "贴 单" in joined
    assert "拆 单" in joined or "拆包贴单" in joined
    assert "2 元 / 单" in joined or "3.5 元 / 单" in joined or "5 元 / 单" in joined
    assert "19130533163" not in sanitize_text("19130533163")


def test_legacy_doc_is_reported_as_unsupported_without_crashing():
    path = WULIU / "oms-对接yandex market店铺授权指南---202412(1)(1).doc"
    hits = extract_legacy_doc(path)
    markdown = render_markdown(hits)

    assert hits[0].status == "unsupported_legacy_doc"
    assert str(path.name) in markdown
    assert "unsupported_legacy_doc" not in markdown


def test_structured_observation_is_stable_sanitized_and_unbound():
    hit = EvidenceHit(
        source_relpath="wuliu/provider.xlsx",
        sha256="a" * 64,
        kind="xlsx",
        location="Rates!A12:F12",
        excerpt=(
            "OZON 运费 50元/kg，退货销毁，联系 19130533163 "
            "或 rates@example.com"
        ),
        currency="CNY",
    )

    first = structured_records([hit])[0]
    replay = structured_records([hit])[0]

    assert first == replay
    assert first["observation_id"].startswith("ru002_")
    assert len(first["observation_sha256"]) == 64
    assert "19130533163" not in first["excerpt"]
    assert "rates@example.com" not in first["excerpt"]
    assert first["mapped_cost_legs"] == [
        "international_logistics",
        "return",
        "damage",
    ]
    assert first["source_excerpt_sanitized"] is True
    assert first["sku_binding"] is None
    assert first["variant_binding"] is None
    assert first["quantity_binding"] is None
    assert first["shipment_profile_binding"] is None
    assert first["effective_period"] is None
    assert first["decision_eligible"] is False
    assert first["actual_cost_created"] is False
    assert first["external_write_allowed"] is False
    assert "amount" not in first
    assert "price" not in first
    assert infer_cost_legs("清关后派送到门") == ("customs", "last_mile")

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from apps.control_plane.ozon_browser_capture_validator import (
    report_sha256,
    validate_capture_bytes,
    validate_capture_file,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CURRENT_CAPTURE = REPO_ROOT / "output" / "playwright" / "ozon-products-evidence.json"


def _item(
    offer_id: str,
    *,
    row_lines: list[str] | None = None,
    currency_code: str | None = None,
    currency_unresolved: bool = True,
) -> dict[str, object]:
    return {
        "external_item_id": offer_id,
        "sku": "sku-1",
        "title": "示例商品",
        "price_display": "10,00 ¥",
        "currency_display": "¥",
        "currency_code": currency_code,
        "currency_unresolved": currency_unresolved,
        "raw_row_lines": row_lines or [offer_id, "SKU sku-1", "10,00 ¥"],
    }


def _artifact(
    *,
    items: list[dict[str, object]] | None = None,
    raw_visible_text: str | None = None,
    item_count: int | None = None,
) -> dict[str, object]:
    rows = items or [_item("offer-a"), _item("offer-b")]
    text = raw_visible_text or "\n".join([line for item in rows for line in item["raw_row_lines"]])
    return {
        "evidence_type": "ozon_browser_visible_dom_observation",
        "evidence_grade": "C",
        "source_profile": "browser_observation",
        "marketplace": "ozon",
        "store_name": "BEIJIXINGYOUXUAN",
        "source_url": "https://seller.ozon.ru/app/products",
        "observed_at": "2026-09-07T00:00:00Z",
        "page_title": "Ozon: Торговая площадка",
        "item_count": len(rows) if item_count is None else item_count,
        "items": rows,
        "raw_visible_text": text,
        "raw_visible_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def _bytes(value: dict[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def test_current_capture_is_quarantined_for_cross_row_and_footer_contamination():
    report = validate_capture_file(
        CURRENT_CAPTURE,
        expected_file_sha256=("f8e7781fdf7ba384d69f548dc08cf59aa36f6aacb62fbb9a8295ecbc2d0b4ae4"),
    )

    assert report["status"] == "QUARANTINED"
    assert report["quarantine"] is True
    assert report["item_count"] == {
        "declared": 17,
        "observed": 17,
        "matches": True,
    }
    assert report["hash_checks"]["raw_visible_text_sha256_matches"] is True
    assert report["hash_checks"]["file_sha256_matches_expected"] is True
    assert report["currency"] == {
        "items_checked": 17,
        "unresolved": 17,
        "resolved": 0,
        "invalid": 0,
    }
    assert "row_contains_other_offer_id" in report["issue_codes"]
    assert "footer_in_row" in report["issue_codes"]
    assert report["rows"]["rows_with_other_offer_id"] == list(range(1, 17))
    assert report["rows"]["rows_with_footer"] == [17]
    assert report["promotion_allowed"] is False
    assert report["external_write_allowed"] is False


def test_clean_capture_is_valid_and_report_hash_is_replayable():
    content = _bytes(_artifact())
    first = validate_capture_bytes(content, artifact_name="capture.json")
    second = validate_capture_bytes(content, artifact_name="capture.json")

    assert first == second
    assert first["status"] == "VALID"
    assert first["issue_count"] == 0
    assert first["file_sha256"] == hashlib.sha256(content).hexdigest()
    assert first["hash_checks"]["raw_visible_text_sha256_matches"] is True
    assert first["currency"] == {
        "items_checked": 2,
        "unresolved": 2,
        "resolved": 0,
        "invalid": 0,
    }
    assert report_sha256(first) == first["report_sha256"]


def test_expected_file_hash_and_declared_file_hash_are_checked():
    value = _artifact()
    content = _bytes(value)
    digest = hashlib.sha256(content).hexdigest()
    value["file_sha256"] = digest
    content_with_declaration = _bytes(value)
    declared_digest = hashlib.sha256(content_with_declaration).hexdigest()
    # A self-declared file hash cannot equal the hash of the bytes containing
    # that declaration.  The validator must expose this mismatch explicitly.
    report = validate_capture_bytes(
        content_with_declaration,
        expected_file_sha256=declared_digest,
    )

    assert report["status"] == "QUARANTINED"
    assert "declared_file_sha256_mismatch" in report["issue_codes"]
    assert "file_sha256_mismatch" not in report["issue_codes"]
    assert report["hash_checks"]["file_sha256_matches_expected"] is True


def test_raw_text_hash_tamper_is_quarantined():
    value = _artifact()
    value["raw_visible_text"] = str(value["raw_visible_text"]) + " tampered"

    report = validate_capture_bytes(_bytes(value))

    assert report["status"] == "QUARANTINED"
    assert "raw_visible_text_sha256_mismatch" in report["issue_codes"]
    assert report["hash_checks"]["raw_visible_text_sha256_matches"] is False


def test_row_boundary_and_footer_checks_are_fail_closed():
    items = [
        _item("offer-a", row_lines=["offer-a", "SKU sku-1", "offer-b"]),
        _item(
            "offer-b",
            row_lines=["offer-b", "返回顶部", "页面行数:", "1-2 从 2"],
        ),
    ]
    report = validate_capture_bytes(_bytes(_artifact(items=items)))

    assert report["status"] == "QUARANTINED"
    assert report["rows"]["rows_with_other_offer_id"] == [1]
    assert report["rows"]["rows_with_footer"] == [2]
    assert "footer_pagination_in_row" in report["issue_codes"]


def test_currency_must_remain_explicitly_unresolved_or_valid_three_letter_code():
    unresolved_with_code = _item(
        "offer-a",
        currency_code="RUB",
        currency_unresolved=True,
    )
    report = validate_capture_bytes(_bytes(_artifact(items=[unresolved_with_code])))
    assert report["status"] == "QUARANTINED"
    assert "currency_unresolved_code_present" in report["issue_codes"]

    resolved = _item(
        "offer-a",
        currency_code="RUB",
        currency_unresolved=False,
    )
    resolved_report = validate_capture_bytes(_bytes(_artifact(items=[resolved])))
    assert resolved_report["status"] == "VALID"
    assert resolved_report["currency"] == {
        "items_checked": 1,
        "unresolved": 0,
        "resolved": 1,
        "invalid": 0,
    }


def test_item_count_and_duplicate_ids_are_reported_without_exposing_raw_text():
    items = [_item("offer-a"), _item("offer-a")]
    report = validate_capture_bytes(_bytes(_artifact(items=items, item_count=3)))

    assert report["status"] == "QUARANTINED"
    assert "item_count_mismatch" in report["issue_codes"]
    assert "duplicate_external_item_id" in report["issue_codes"]
    assert "raw_visible_text" not in report
    assert all("title" not in issue for issue in report["issues"])


def test_unreadable_file_returns_deterministic_quarantine_report(tmp_path):
    missing = tmp_path / "missing.json"

    first = validate_capture_file(missing)
    second = validate_capture_file(missing)

    assert first == second
    assert first["status"] == "QUARANTINED"
    assert first["issue_codes"] == ["artifact_unreadable"]
    assert first["file_sha256"] is None

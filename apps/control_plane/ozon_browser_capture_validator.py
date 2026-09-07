"""Validate an Ozon visible-DOM capture without promoting its contents.

The browser capture produced during the current Ozon observation is a local,
C-grade evidence artifact.  It is useful for review only after the artifact
itself has passed structural checks.  In particular, a line-oriented parser
must not silently attach the next product (or the page footer) to the current
product.  This module is deliberately side-effect free: it reads bytes,
computes hashes and returns a deterministic report.  It never calls a browser,
an Ozon endpoint, the control-plane API or an Evidence repository.

``QUARANTINED`` is fail-closed.  A quarantined capture can remain available as
raw evidence, but it must not be promoted to a formal observation or used to
authorize a marketplace action.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

_CONTRACT_ID = "kjds-ozon-browser-capture-validator-v1"
_CONTRACT_VERSION = "1.0.0"
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_CURRENCY_CODE_RE = re.compile(r"^[A-Z]{3}$")
_PAGINATION_RE = re.compile(r"^\d+\s*-\s*\d+\s+从\s+\d+$")
_FOOTER_MARKERS = (
    "返回顶部",
    "页面行数",
    "无法获取限额信息",
    "©",
    "copyright",
)

CONTRACT_ID = _CONTRACT_ID
CONTRACT_VERSION = _CONTRACT_VERSION
ValidationStatus = Literal["VALID", "QUARANTINED"]


def _canonical(value: Any) -> bytes:
    """Return the stable UTF-8 JSON representation used for report hashes."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _nonempty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _issue(
    code: str,
    *,
    item_index: int | None = None,
    external_item_id: str | None = None,
    line_index: int | None = None,
    foreign_offer_id: str | None = None,
    field: str | None = None,
) -> dict[str, Any]:
    """Build a redacted, stable issue object.

    Only row indexes, stable item IDs and machine-readable codes are returned;
    product titles and raw page text are intentionally excluded from reports.
    """

    result: dict[str, Any] = {"code": code}
    if item_index is not None:
        result["item_index"] = item_index
    if external_item_id is not None:
        result["external_item_id"] = external_item_id
    if line_index is not None:
        result["line_index"] = line_index
    if foreign_offer_id is not None:
        result["foreign_offer_id"] = foreign_offer_id
    if field is not None:
        result["field"] = field
    return result


def _issue_sort_key(value: Mapping[str, Any]) -> tuple[str, int, int, str, str, str]:
    return (
        str(value.get("code") or ""),
        int(value.get("item_index") or 0),
        int(value.get("line_index") or 0),
        str(value.get("external_item_id") or ""),
        str(value.get("foreign_offer_id") or ""),
        str(value.get("field") or ""),
    )


def _footer_code(line: str) -> str | None:
    """Return a stable footer code for one visible line, if present."""

    stripped = line.strip()
    lowered = stripped.casefold()
    if _PAGINATION_RE.fullmatch(stripped):
        return "footer_pagination_in_row"
    if any(marker.casefold() in lowered for marker in _FOOTER_MARKERS):
        return "footer_in_row"
    return None


def _row_issue_summary(issues: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    foreign_rows = sorted(
        {
            int(item["item_index"])
            for item in issues
            if item.get("code") == "row_contains_other_offer_id" and isinstance(item.get("item_index"), int)
        }
    )
    footer_rows = sorted(
        {
            int(item["item_index"])
            for item in issues
            if str(item.get("code", "")).startswith("footer_") and isinstance(item.get("item_index"), int)
        }
    )
    first_mismatch_rows = sorted(
        {
            int(item["item_index"])
            for item in issues
            if item.get("code") == "row_first_line_mismatch" and isinstance(item.get("item_index"), int)
        }
    )
    return {
        "rows_checked": 0,
        "rows_with_other_offer_id": foreign_rows,
        "rows_with_footer": footer_rows,
        "rows_with_first_line_mismatch": first_mismatch_rows,
    }


def _report_payload(
    *,
    artifact_name: str,
    file_sha256: str | None,
    expected_file_sha256: str | None,
    supplied_raw_hash: str | None,
    computed_raw_hash: str | None,
    declared_file_hash: str | None,
    item_count_declared: Any,
    item_count_observed: int,
    currency_summary: dict[str, int],
    row_summary: dict[str, Any],
    issues: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    ordered_issues = [dict(item) for item in sorted(issues, key=_issue_sort_key)]
    unique_codes = sorted({str(item.get("code")) for item in ordered_issues})
    file_matches_expected = (
        None
        if expected_file_sha256 is None or file_sha256 is None
        else file_sha256.lower() == expected_file_sha256.lower()
    )
    file_matches_declared = (
        None if declared_file_hash is None or file_sha256 is None else file_sha256.lower() == declared_file_hash.lower()
    )
    raw_hash_matches = (
        None
        if supplied_raw_hash is None or computed_raw_hash is None
        else _is_sha256(supplied_raw_hash) and supplied_raw_hash.lower() == computed_raw_hash.lower()
    )
    report: dict[str, Any] = {
        "contract_id": _CONTRACT_ID,
        "contract_version": _CONTRACT_VERSION,
        "artifact_name": artifact_name,
        "file_sha256": file_sha256,
        "expected_file_sha256": expected_file_sha256,
        "declared_file_sha256": declared_file_hash,
        "hash_checks": {
            "file_sha256_matches_expected": file_matches_expected,
            "file_sha256_matches_declared": file_matches_declared,
            "raw_visible_text_sha256_matches": raw_hash_matches,
        },
        "raw_visible_text_sha256": supplied_raw_hash,
        "computed_raw_visible_text_sha256": computed_raw_hash,
        "item_count": {
            "declared": item_count_declared,
            "observed": item_count_observed,
            "matches": (
                isinstance(item_count_declared, int)
                and not isinstance(item_count_declared, bool)
                and item_count_declared == item_count_observed
            ),
        },
        "currency": currency_summary,
        "rows": row_summary,
        "issue_count": len(ordered_issues),
        "issue_codes": unique_codes,
        "issues": ordered_issues,
        "status": "QUARANTINED" if ordered_issues else "VALID",
        "quarantine": bool(ordered_issues),
        "promotion_allowed": False,
        "formal_observation_allowed": False,
        "external_write_allowed": False,
    }
    return report


def _with_report_hash(report: Mapping[str, Any]) -> dict[str, Any]:
    payload = {str(key): value for key, value in report.items() if key != "report_sha256"}
    result = dict(payload)
    result["report_sha256"] = _sha256(_canonical(payload))
    return result


def report_sha256(report: Mapping[str, Any]) -> str:
    """Compute the deterministic digest of a validator report."""

    return _sha256(_canonical({str(key): value for key, value in report.items() if key != "report_sha256"}))


def validate_capture_bytes(
    content: bytes,
    *,
    artifact_name: str = "ozon-products-evidence.json",
    expected_file_sha256: str | None = None,
) -> dict[str, Any]:
    """Validate one capture byte string and return a deterministic report.

    The function never writes the bytes or a report.  All ordinary malformed
    input is represented as a ``QUARANTINED`` report so callers can safely
    persist the report without accidentally treating an exception as success.
    """

    if not isinstance(content, bytes):
        raise TypeError("content must be bytes")
    if not isinstance(artifact_name, str) or not artifact_name.strip():
        raise ValueError("artifact_name must be non-empty")
    if expected_file_sha256 is not None and not _is_sha256(expected_file_sha256):
        raise ValueError("expected_file_sha256 must be a 64-character SHA-256")

    file_digest = _sha256(content)
    issues: list[dict[str, Any]] = []
    if expected_file_sha256 is not None and file_digest.lower() != expected_file_sha256.lower():
        issues.append(_issue("file_sha256_mismatch"))

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        issues.append(_issue("artifact_utf8_invalid"))
        return _with_report_hash(
            _report_payload(
                artifact_name=Path(artifact_name).name,
                file_sha256=file_digest,
                expected_file_sha256=expected_file_sha256,
                supplied_raw_hash=None,
                computed_raw_hash=None,
                declared_file_hash=None,
                item_count_declared=None,
                item_count_observed=0,
                currency_summary={
                    "items_checked": 0,
                    "unresolved": 0,
                    "resolved": 0,
                    "invalid": 0,
                },
                row_summary={
                    "rows_checked": 0,
                    "rows_with_other_offer_id": [],
                    "rows_with_footer": [],
                    "rows_with_first_line_mismatch": [],
                },
                issues=issues,
            )
        )

    try:
        document = json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError):
        issues.append(_issue("artifact_json_invalid"))
        return _with_report_hash(
            _report_payload(
                artifact_name=Path(artifact_name).name,
                file_sha256=file_digest,
                expected_file_sha256=expected_file_sha256,
                supplied_raw_hash=None,
                computed_raw_hash=None,
                declared_file_hash=None,
                item_count_declared=None,
                item_count_observed=0,
                currency_summary={
                    "items_checked": 0,
                    "unresolved": 0,
                    "resolved": 0,
                    "invalid": 0,
                },
                row_summary={
                    "rows_checked": 0,
                    "rows_with_other_offer_id": [],
                    "rows_with_footer": [],
                    "rows_with_first_line_mismatch": [],
                },
                issues=issues,
            )
        )

    if not isinstance(document, Mapping):
        issues.append(_issue("artifact_root_not_object"))
        return _with_report_hash(
            _report_payload(
                artifact_name=Path(artifact_name).name,
                file_sha256=file_digest,
                expected_file_sha256=expected_file_sha256,
                supplied_raw_hash=None,
                computed_raw_hash=None,
                declared_file_hash=None,
                item_count_declared=None,
                item_count_observed=0,
                currency_summary={
                    "items_checked": 0,
                    "unresolved": 0,
                    "resolved": 0,
                    "invalid": 0,
                },
                row_summary={
                    "rows_checked": 0,
                    "rows_with_other_offer_id": [],
                    "rows_with_footer": [],
                    "rows_with_first_line_mismatch": [],
                },
                issues=issues,
            )
        )

    data = dict(document)
    required_fields = (
        "evidence_type",
        "evidence_grade",
        "source_profile",
        "marketplace",
        "store_name",
        "source_url",
        "observed_at",
        "item_count",
        "items",
        "raw_visible_text",
        "raw_visible_text_sha256",
    )
    for field in required_fields:
        if field not in data:
            issues.append(_issue("artifact_field_missing", field=field))

    if data.get("evidence_type") != "ozon_browser_visible_dom_observation":
        issues.append(_issue("evidence_type_invalid"))
    if data.get("evidence_grade") != "C":
        issues.append(_issue("evidence_grade_invalid"))
    if data.get("marketplace") != "ozon":
        issues.append(_issue("marketplace_invalid"))
    for field in ("source_profile", "store_name", "source_url", "observed_at"):
        if not _nonempty_text(data.get(field)):
            issues.append(_issue("artifact_field_invalid", field=field))

    raw_text = data.get("raw_visible_text")
    supplied_raw_hash = data.get("raw_visible_text_sha256")
    computed_raw_hash: str | None = None
    if isinstance(raw_text, str):
        computed_raw_hash = _sha256(raw_text.encode("utf-8"))
        if not _is_sha256(supplied_raw_hash):
            issues.append(_issue("raw_visible_text_sha256_invalid", field="raw_visible_text_sha256"))
        elif supplied_raw_hash.lower() != computed_raw_hash:
            issues.append(_issue("raw_visible_text_sha256_mismatch"))
    else:
        issues.append(_issue("artifact_field_invalid", field="raw_visible_text"))
        if supplied_raw_hash is not None and not _is_sha256(supplied_raw_hash):
            issues.append(_issue("raw_visible_text_sha256_invalid", field="raw_visible_text_sha256"))

    declared_file_hash = data.get("file_sha256")
    if declared_file_hash is not None:
        if not _is_sha256(declared_file_hash):
            issues.append(_issue("declared_file_sha256_invalid", field="file_sha256"))
        elif declared_file_hash.lower() != file_digest:
            issues.append(_issue("declared_file_sha256_mismatch"))

    items = data.get("items")
    item_count_declared = data.get("item_count")
    if not isinstance(items, list):
        issues.append(_issue("items_not_array", field="items"))
        items_list: list[Any] = []
    else:
        items_list = items
    item_count_observed = len(items_list)
    if not isinstance(item_count_declared, int) or isinstance(item_count_declared, bool):
        issues.append(_issue("item_count_invalid", field="item_count"))
    elif item_count_declared != item_count_observed:
        issues.append(_issue("item_count_mismatch", field="item_count"))
    if not items_list:
        issues.append(_issue("items_empty", field="items"))

    indexed_item_ids: list[tuple[int, str]] = []
    for index, item in enumerate(items_list, 1):
        if isinstance(item, Mapping) and _nonempty_text(item.get("external_item_id")):
            indexed_item_ids.append((index, str(item["external_item_id"]).strip()))
    item_ids = [item_id for _index, item_id in indexed_item_ids]
    all_ids = set(item_ids)
    seen_ids: set[str] = set()
    if len(item_ids) != len(set(item_ids)):
        # Emit one issue per repeated ID, in item order, rather than depending
        # on set iteration order.
        for index, item_id in indexed_item_ids:
            if item_id in seen_ids:
                issues.append(
                    _issue(
                        "duplicate_external_item_id",
                        item_index=index,
                        external_item_id=item_id,
                    )
                )
            seen_ids.add(item_id)

    raw_id_lines: set[str] = set()
    raw_lines_sequence: list[str] = []
    if isinstance(raw_text, str):
        raw_lines_sequence = [line.strip() for line in raw_text.splitlines() if line.strip()]
        raw_id_lines = set(raw_lines_sequence)

    currency_summary = {
        "items_checked": 0,
        "unresolved": 0,
        "resolved": 0,
        "invalid": 0,
    }
    row_summary = {
        "rows_checked": 0,
        "rows_with_other_offer_id": [],
        "rows_with_footer": [],
        "rows_with_first_line_mismatch": [],
    }

    raw_item_positions: list[tuple[int, int, str]] = []
    for index, raw_item in enumerate(items_list, 1):
        if not isinstance(raw_item, Mapping):
            issues.append(_issue("item_not_object", item_index=index))
            continue
        item = dict(raw_item)
        item_id_value = item.get("external_item_id")
        item_id = str(item_id_value).strip() if _nonempty_text(item_id_value) else None
        if item_id is None:
            issues.append(_issue("external_item_id_missing", item_index=index))
        elif item_id not in raw_id_lines:
            issues.append(
                _issue(
                    "external_item_id_missing_from_raw_visible_text",
                    item_index=index,
                    external_item_id=item_id,
                )
            )
        else:
            positions = [position for position, line in enumerate(raw_lines_sequence) if line == item_id]
            if len(positions) > 1:
                issues.append(
                    _issue(
                        "external_item_id_repeated_in_raw_visible_text",
                        item_index=index,
                        external_item_id=item_id,
                    )
                )
            if positions:
                raw_item_positions.append((index, positions[0], item_id))

        price_display = item.get("price_display")
        if not _nonempty_text(price_display):
            issues.append(_issue("price_display_missing", item_index=index, external_item_id=item_id))

        currency_summary["items_checked"] += 1
        currency_display = item.get("currency_display")
        currency_code = item.get("currency_code")
        unresolved = item.get("currency_unresolved")
        currency_bad = False
        if not _nonempty_text(currency_display):
            issues.append(_issue("currency_display_missing", item_index=index, external_item_id=item_id))
            currency_bad = True
        if not isinstance(unresolved, bool):
            issues.append(_issue("currency_unresolved_invalid", item_index=index, external_item_id=item_id))
            currency_bad = True
        elif unresolved:
            if currency_code is not None:
                issues.append(
                    _issue(
                        "currency_unresolved_code_present",
                        item_index=index,
                        external_item_id=item_id,
                    )
                )
                currency_bad = True
            currency_summary["unresolved"] += 1
        else:
            if not (isinstance(currency_code, str) and _CURRENCY_CODE_RE.fullmatch(currency_code) is not None):
                issues.append(
                    _issue(
                        "currency_code_invalid",
                        item_index=index,
                        external_item_id=item_id,
                    )
                )
                currency_bad = True
            currency_summary["resolved"] += 1
        if currency_bad:
            currency_summary["invalid"] += 1

        raw_rows = item.get("raw_row_lines")
        row_summary["rows_checked"] += 1
        if not isinstance(raw_rows, list) or not raw_rows:
            issues.append(_issue("raw_row_lines_invalid", item_index=index, external_item_id=item_id))
            continue
        normalized_rows: list[str] = []
        for line_index, raw_line in enumerate(raw_rows, 1):
            if not isinstance(raw_line, str):
                issues.append(
                    _issue(
                        "raw_row_line_not_text",
                        item_index=index,
                        external_item_id=item_id,
                        line_index=line_index,
                    )
                )
                continue
            normalized_rows.append(raw_line.strip())
            footer_code = _footer_code(raw_line)
            if footer_code is not None:
                issues.append(
                    _issue(
                        footer_code,
                        item_index=index,
                        external_item_id=item_id,
                        line_index=line_index,
                    )
                )

        first_nonempty = next((line for line in normalized_rows if line), None)
        if item_id is None or first_nonempty != item_id:
            issues.append(
                _issue(
                    "row_first_line_mismatch",
                    item_index=index,
                    external_item_id=item_id,
                )
            )
        elif normalized_rows.count(item_id) > 1:
            issues.append(
                _issue(
                    "row_contains_duplicate_own_offer_id",
                    item_index=index,
                    external_item_id=item_id,
                )
            )

        for line_index, line in enumerate(normalized_rows, 1):
            if line in all_ids and line != item_id:
                issues.append(
                    _issue(
                        "row_contains_other_offer_id",
                        item_index=index,
                        external_item_id=item_id,
                        line_index=line_index,
                        foreign_offer_id=line,
                    )
                )

    previous_position: int | None = None
    for index, position, item_id in raw_item_positions:
        if previous_position is not None and position <= previous_position:
            issues.append(
                _issue(
                    "raw_offer_id_order_mismatch",
                    item_index=index,
                    external_item_id=item_id,
                )
            )
        previous_position = position

    row_summary = _row_issue_summary(issues) | {
        "rows_checked": row_summary["rows_checked"],
    }
    report = _report_payload(
        artifact_name=Path(artifact_name).name,
        file_sha256=file_digest,
        expected_file_sha256=expected_file_sha256,
        supplied_raw_hash=(supplied_raw_hash if isinstance(supplied_raw_hash, str) else None),
        computed_raw_hash=computed_raw_hash,
        declared_file_hash=(declared_file_hash if isinstance(declared_file_hash, str) else None),
        item_count_declared=item_count_declared,
        item_count_observed=item_count_observed,
        currency_summary=currency_summary,
        row_summary=row_summary,
        issues=issues,
    )
    return _with_report_hash(report)


def validate_capture_file(
    path: str | Path,
    *,
    expected_file_sha256: str | None = None,
) -> dict[str, Any]:
    """Read and validate a local artifact; never write to it or elsewhere."""

    artifact = Path(path)
    try:
        content = artifact.read_bytes()
    except (OSError, ValueError):
        # There is no file digest to claim when the read itself failed.  Keep
        # the report deterministic and machine-readable instead of raising a
        # success-looking empty result.
        report = _report_payload(
            artifact_name=artifact.name,
            file_sha256=None,
            expected_file_sha256=expected_file_sha256,
            supplied_raw_hash=None,
            computed_raw_hash=None,
            declared_file_hash=None,
            item_count_declared=None,
            item_count_observed=0,
            currency_summary={
                "items_checked": 0,
                "unresolved": 0,
                "resolved": 0,
                "invalid": 0,
            },
            row_summary={
                "rows_checked": 0,
                "rows_with_other_offer_id": [],
                "rows_with_footer": [],
                "rows_with_first_line_mismatch": [],
            },
            issues=[_issue("artifact_unreadable")],
        )
        return _with_report_hash(report)
    return validate_capture_bytes(
        content,
        artifact_name=artifact.name,
        expected_file_sha256=expected_file_sha256,
    )


def validate_capture(
    path: str | Path,
    *,
    expected_file_sha256: str | None = None,
) -> dict[str, Any]:
    """Compatibility alias for callers that use the shorter verb form."""

    return validate_capture_file(
        path,
        expected_file_sha256=expected_file_sha256,
    )


def _main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a local Ozon visible-DOM capture without external access.")
    parser.add_argument(
        "path",
        nargs="?",
        default="output/playwright/ozon-products-evidence.json",
        help="path to the local capture JSON",
    )
    parser.add_argument(
        "--expected-file-sha256",
        default=None,
        help="optional expected SHA-256 for the artifact bytes",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="pretty-print the deterministic JSON report",
    )
    args = parser.parse_args(argv)
    try:
        report = validate_capture_file(
            args.path,
            expected_file_sha256=args.expected_file_sha256,
        )
    except (TypeError, ValueError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            report,
            ensure_ascii=False,
            sort_keys=True,
            indent=2 if args.pretty else None,
            separators=None if args.pretty else (",", ":"),
        )
    )
    return 0 if report["status"] == "VALID" else 2


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point retained for ``python -m`` and script wrappers."""

    return _main(argv)


if __name__ == "__main__":  # pragma: no cover - exercised by CLI smoke tests
    sys.exit(main())


__all__ = [
    "CONTRACT_ID",
    "CONTRACT_VERSION",
    "ValidationStatus",
    "main",
    "report_sha256",
    "validate_capture",
    "validate_capture_bytes",
    "validate_capture_file",
]

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

CONTRACT = {
    "candidate-research.csv": (
        "candidate_ref",
        "candidate_name",
        "market",
        "channel",
        "category",
        "metric",
        "value",
        "confidence",
        "window_days",
        "sample_size",
        "evidence_reference",
        "source_family",
        "observed_at",
        "owner",
        "status",
    ),
    "g0-governance.csv": (
        "field",
        "value",
        "evidence_reference",
        "owner",
        "status",
    ),
    "g0-ozon-access.csv": (
        "field",
        "value",
        "evidence_reference",
        "owner",
        "status",
    ),
    "g0-ozon-api-identities.csv": (
        "identity_ref",
        "purpose",
        "caller_system",
        "owner",
        "role_count",
        "scope_class",
        "last_used_at",
        "disposition",
        "evidence_reference",
        "reviewed_by",
        "status",
        "notes",
    ),
    "sku-passports.csv": (
        "sku",
        "product_name",
        "material",
        "intended_use",
        "country_of_origin",
        "weight_kg",
        "length_cm",
        "width_cm",
        "height_cm",
        "product_evidence",
        "hs_code",
        "eaeu_rules",
        "eac_requirement",
        "chestny_znak_requirement",
        "russian_labeling",
        "ip_status",
        "transport_restrictions",
        "sellability",
        "compliance_evidence",
        "golden_sample_ref",
        "inspection_plan",
        "packaging_test",
        "quality_evidence",
        "owner",
        "status",
    ),
    "supplier-quotes.csv": (
        "sku",
        "supplier_ref",
        "platform",
        "external_quote_id",
        "source_url",
        "title",
        "currency",
        "unit_price",
        "source_to_cny_rate",
        "moq",
        "weight_kg",
        "length_cm",
        "width_cm",
        "height_cm",
        "domestic_logistics_per_unit",
        "evidence_reference",
        "quoted_at",
        "owner",
        "status",
    ),
    "sku-media.csv": (
        "sku",
        "variant_id",
        "asset_role",
        "source_kind",
        "source_reference",
        "rights_evidence_reference",
        "captured_at",
        "sha256",
        "planned_use",
        "owner",
        "status",
        "notes",
    ),
    "finance-reconciliation.csv": (
        "reconciliation_key",
        "currency",
        "order_receivable",
        "explained_fees",
        "adjustments",
        "expected_settlement",
        "platform_settlement",
        "bank_receipt",
        "fx_source",
        "fx_rate",
        "fx_effective_at",
        "unknown_fee_amount",
        "evidence_reference",
        "owner",
        "status",
    ),
}

REQUIRED_MEDIA_ROLES = {
    "front_main",
    "back",
    "side",
    "detail",
    "accessories",
    "packaging",
    "scale_reference",
}
ALLOWED_MEDIA_SOURCE_KINDS = {"sample_photo", "supplier_authorized"}
ALLOWED_MEDIA_STATUSES = {"pending", "captured", "verified", "rejected"}
SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
UNRESOLVED_VALUES = {"", "draft", "pending", "pending_review", "required", "review_required", "unknown"}

REQUIRED_FIELD_ROWS = {
    "g0-governance.csv": {
        "business_owner",
        "independent_approver",
        "monthly_risk_budget_cny",
        "maximum_single_loss_cny",
        "rollback_authority",
        "forbidden_actions",
    },
    "g0-ozon-access.csv": {
        "account_alias",
        "seller_or_client_id",
        "legal_entity",
        "allowed_read_operations",
        "forbidden_write_operations",
        "payout_path_masked",
        "credential_owner",
        "permission_verified_at",
        "note",
    },
}

SENSITIVE_NAME = re.compile(
    r"password|api[_-]?key|access[_-]?token|refresh[_-]?token|secret|bank[_-]?account|personal[_-]?id|passport[_-]?number",
    re.IGNORECASE,
)

REVIEW_FIELDS = {
    "candidate-research.csv": (
        "candidate_name",
        "category",
        "value",
        "confidence",
        "evidence_reference",
        "source_family",
        "observed_at",
        "owner",
        "status",
    ),
    "g0-governance.csv": ("value", "evidence_reference", "owner", "status"),
    "g0-ozon-access.csv": ("value", "evidence_reference", "owner", "status"),
    "g0-ozon-api-identities.csv": (
        "purpose",
        "caller_system",
        "owner",
        "role_count",
        "scope_class",
        "last_used_at",
        "disposition",
        "evidence_reference",
        "reviewed_by",
        "status",
    ),
    "sku-passports.csv": tuple(
        field
        for field in CONTRACT["sku-passports.csv"]
        if field not in {"sku"}
    ),
    "supplier-quotes.csv": tuple(
        field
        for field in CONTRACT["supplier-quotes.csv"]
        if field not in {"sku", "supplier_ref", "source_url"}
    ),
    "finance-reconciliation.csv": tuple(
        field
        for field in CONTRACT["finance-reconciliation.csv"]
        if field not in {"reconciliation_key"}
    ),
}

CANDIDATE_MEASUREMENT_CONTRACTS = {
    "demand_signal": (28, 90, 30),
    "competition_gap": (28, 90, 30),
    "supplier_available": (1, 90, 1),
    "compliance_redline": (1, 90, 1),
    "return_risk": (28, 90, 30),
}


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]], str]:
    raw = path.read_bytes()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        rows = list(reader)
    return headers, rows, hashlib.sha256(raw).hexdigest()


def _submission_readiness(
    rows_by_file: dict[str, list[dict[str, str]]],
    known_skus: set[str],
) -> dict:
    sections: dict[str, dict] = {}
    for filename, required_fields in REVIEW_FIELDS.items():
        blockers = []
        rows = rows_by_file.get(filename, [])
        for index, row in enumerate(rows, start=2):
            row_fields = ("value",) if filename == "g0-ozon-access.csv" and row.get("field") == "note" else required_fields
            unresolved = [
                field
                for field in row_fields
                if row.get(field, "").strip().casefold() in UNRESOLVED_VALUES
            ]
            if unresolved:
                if row.get("sku") and row.get("supplier_ref"):
                    identity = f"{row['sku']}/{row['supplier_ref']}"
                elif row.get("candidate_ref") and row.get("metric"):
                    identity = f"{row['candidate_ref']}/{row['metric']}"
                else:
                    identity = (
                        row.get("field")
                        or row.get("sku")
                        or row.get("reconciliation_key")
                        or f"row-{index}"
                    )
                blockers.append(
                    {
                        "row": index,
                        "identity": identity,
                        "unresolved_fields": unresolved,
                    }
                )
        sections[filename] = {
            "status": "ready_for_human_review" if rows and not blockers else "awaiting_inputs",
            "row_count": len(rows),
            "blocked_rows": len(blockers),
            "blockers": blockers,
        }

    media_blockers = []
    verified_by_sku = {sku: set() for sku in known_skus}
    for row in rows_by_file.get("sku-media.csv", []):
        sku = row.get("sku", "").strip()
        if (
            sku in known_skus
            and row.get("variant_id", "").strip() == "base"
            and row.get("status", "").strip() == "verified"
        ):
            verified_by_sku[sku].add(row.get("asset_role", "").strip())
    for sku in sorted(known_skus):
        missing = sorted(REQUIRED_MEDIA_ROLES - verified_by_sku[sku])
        if missing:
            media_blockers.append({"sku": sku, "unverified_roles": missing})
    sections["sku-media.csv"] = {
        "status": "ready_for_human_review" if known_skus and not media_blockers else "awaiting_inputs",
        "row_count": len(rows_by_file.get("sku-media.csv", [])),
        "blocked_rows": len(media_blockers),
        "blockers": media_blockers,
    }

    candidate_rows = rows_by_file.get("candidate-research.csv", [])
    candidate_blockers = sections["candidate-research.csv"]["blockers"]
    candidate_refs = sorted({row.get("candidate_ref", "").strip() for row in candidate_rows if row.get("candidate_ref", "").strip()})
    for candidate_ref in candidate_refs:
        source_families = {
            row.get("source_family", "").strip().casefold()
            for row in candidate_rows
            if row.get("candidate_ref", "").strip() == candidate_ref
            and row.get("source_family", "").strip()
        }
        if len(source_families) < 2:
            candidate_blockers.append(
                {
                    "identity": candidate_ref,
                    "unresolved_fields": ["at_least_two_independent_source_families"],
                }
            )
    sections["candidate-research.csv"].update(
        {
            "status": "ready_for_human_review" if candidate_rows and not candidate_blockers else "awaiting_inputs",
            "blocked_rows": len(candidate_blockers),
        }
    )

    blocked_sections = sorted(
        filename for filename, section in sections.items() if section["status"] != "ready_for_human_review"
    )
    return {
        "status": "ready_for_human_intake" if not blocked_sections else "awaiting_inputs",
        "ready_sections": sorted(set(sections) - set(blocked_sections)),
        "blocked_sections": blocked_sections,
        "sections": sections,
        "automatic_import": False,
        "formal_fact_promoted": False,
        "warning": (
            "Review readiness only checks required values and evidence references are present. "
            "It does not validate the referenced evidence or approve any Gate."
        ),
    }


def validate_startup_package(directory: Path) -> dict:
    errors: list[str] = []
    files: dict[str, dict] = {}
    rows_by_file: dict[str, list[dict[str, str]]] = {}

    for filename, expected_headers in CONTRACT.items():
        path = directory / filename
        if not path.is_file():
            errors.append(f"{filename}: required file is missing")
            continue
        headers, rows, digest = _read_csv(path)
        rows_by_file[filename] = rows
        files[filename] = {"rows": len(rows), "sha256": digest}
        if tuple(headers) != expected_headers:
            errors.append(f"{filename}: header contract mismatch")
        sensitive_headers = sorted(header for header in headers if SENSITIVE_NAME.search(header))
        if sensitive_headers:
            errors.append(f"{filename}: sensitive headers are forbidden: {', '.join(sensitive_headers)}")
        if any(None in row for row in rows):
            errors.append(f"{filename}: one or more rows contain values outside the declared columns")

    for filename, required_fields in REQUIRED_FIELD_ROWS.items():
        rows = rows_by_file.get(filename, [])
        actual_fields = [row.get("field", "").strip() for row in rows]
        if len(actual_fields) != len(set(actual_fields)):
            errors.append(f"{filename}: field names must be unique")
        missing = sorted(required_fields - set(actual_fields))
        unexpected = sorted(set(actual_fields) - required_fields)
        if missing:
            errors.append(f"{filename}: required field rows missing: {', '.join(missing)}")
        if unexpected:
            errors.append(f"{filename}: unexpected field rows: {', '.join(unexpected)}")
        sensitive_fields = sorted(field for field in actual_fields if SENSITIVE_NAME.search(field))
        if sensitive_fields:
            errors.append(f"{filename}: sensitive field names are forbidden: {', '.join(sensitive_fields)}")

    identity_rows = rows_by_file.get("g0-ozon-api-identities.csv", [])
    identity_refs = [row.get("identity_ref", "").strip() for row in identity_rows]
    if not identity_rows:
        errors.append("g0-ozon-api-identities.csv: at least one identity inventory row is required")
    if any(not identity_ref for identity_ref in identity_refs):
        errors.append("g0-ozon-api-identities.csv: every row requires identity_ref")
    if len(identity_refs) != len(set(identity_refs)):
        errors.append("g0-ozon-api-identities.csv: identity_ref values must be unique")

    candidate_rows = rows_by_file.get("candidate-research.csv", [])
    candidate_refs = {row.get("candidate_ref", "").strip() for row in candidate_rows if row.get("candidate_ref", "").strip()}
    candidate_keys: list[tuple[str, str]] = []
    if len(candidate_refs) != 3:
        errors.append("candidate-research.csv: exactly three unique non-empty candidate_ref values are required")
    for row in candidate_rows:
        candidate_ref = row.get("candidate_ref", "").strip()
        metric = row.get("metric", "").strip()
        if not candidate_ref or not metric:
            errors.append("candidate-research.csv: every row requires candidate_ref and metric")
            continue
        if row.get("market", "").strip().upper() != "RU" or row.get("channel", "").strip().upper() != "OZON":
            errors.append(f"candidate-research.csv: {candidate_ref}/{metric} must target RU/OZON")
        contract = CANDIDATE_MEASUREMENT_CONTRACTS.get(metric)
        if contract is None:
            errors.append(f"candidate-research.csv: unsupported metric for {candidate_ref}: {metric}")
            continue
        candidate_keys.append((candidate_ref, metric))
        try:
            window_days = int(row.get("window_days", ""))
            sample_size = int(row.get("sample_size", ""))
        except ValueError:
            errors.append(f"candidate-research.csv: invalid window or sample for {candidate_ref}/{metric}")
            continue
        min_window, max_window, min_sample = contract
        if not min_window <= window_days <= max_window or sample_size < min_sample:
            errors.append(f"candidate-research.csv: measurement contract mismatch for {candidate_ref}/{metric}")
        raw_value = row.get("value", "").strip()
        raw_confidence = row.get("confidence", "").strip()
        if raw_value:
            try:
                value = Decimal(raw_value)
            except InvalidOperation:
                errors.append(f"candidate-research.csv: invalid value for {candidate_ref}/{metric}")
            else:
                if not value.is_finite() or not 0 <= value <= 100 or (
                    metric in {"supplier_available", "compliance_redline"} and value not in {0, 1}
                ):
                    errors.append(f"candidate-research.csv: value outside metric range for {candidate_ref}/{metric}")
        if raw_confidence:
            try:
                confidence = Decimal(raw_confidence)
            except InvalidOperation:
                errors.append(f"candidate-research.csv: invalid confidence for {candidate_ref}/{metric}")
            else:
                if not confidence.is_finite() or not 0 < confidence <= 1:
                    errors.append(f"candidate-research.csv: confidence must be in (0, 1] for {candidate_ref}/{metric}")
        observed_at = row.get("observed_at", "").strip()
        if observed_at:
            try:
                parsed_at = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
            except ValueError:
                parsed_at = None
            if parsed_at is None or parsed_at.tzinfo is None:
                errors.append(f"candidate-research.csv: observed_at must include timezone for {candidate_ref}/{metric}")
    if len(candidate_keys) != len(set(candidate_keys)):
        errors.append("candidate-research.csv: duplicate candidate_ref/metric rows are forbidden")
    for candidate_ref in sorted(candidate_refs):
        actual_metrics = {metric for ref, metric in candidate_keys if ref == candidate_ref}
        if actual_metrics != set(CANDIDATE_MEASUREMENT_CONTRACTS):
            errors.append(f"candidate-research.csv: {candidate_ref} requires each fixed metric exactly once")
        candidate_names = {
            row.get("candidate_name", "").strip()
            for row in candidate_rows
            if row.get("candidate_ref", "").strip() == candidate_ref and row.get("candidate_name", "").strip()
        }
        categories = {
            row.get("category", "").strip()
            for row in candidate_rows
            if row.get("candidate_ref", "").strip() == candidate_ref and row.get("category", "").strip()
        }
        if len(candidate_names) > 1 or len(categories) > 1:
            errors.append(f"candidate-research.csv: {candidate_ref} must use one candidate_name and category")

    passport_rows = rows_by_file.get("sku-passports.csv", [])
    skus = [row.get("sku", "").strip() for row in passport_rows]
    known_skus = {sku for sku in skus if sku}
    if len(skus) != 3 or len(known_skus) != 3:
        errors.append("sku-passports.csv: exactly three unique non-empty SKU rows are required")

    quote_rows = rows_by_file.get("supplier-quotes.csv", [])
    quote_pairs: list[tuple[str, str]] = []
    suppliers_by_sku = {sku: set() for sku in known_skus}
    for row in quote_rows:
        sku = row.get("sku", "").strip()
        supplier = row.get("supplier_ref", "").strip()
        if not sku or not supplier:
            errors.append("supplier-quotes.csv: every row requires sku and supplier_ref")
            continue
        if sku not in known_skus:
            errors.append(f"supplier-quotes.csv: unknown SKU reference: {sku}")
            continue
        quote_pairs.append((sku, supplier))
        suppliers_by_sku[sku].add(supplier)
    if len(quote_pairs) != len(set(quote_pairs)):
        errors.append("supplier-quotes.csv: duplicate sku/supplier_ref pairs are forbidden")
    for sku in sorted(known_skus):
        if len(suppliers_by_sku[sku]) != 3:
            errors.append(f"supplier-quotes.csv: {sku} requires exactly three distinct suppliers")

    media_rows = rows_by_file.get("sku-media.csv", [])
    media_keys: list[tuple[str, str, str]] = []
    base_media_roles = {sku: set() for sku in known_skus}
    for row in media_rows:
        sku = row.get("sku", "").strip()
        variant_id = row.get("variant_id", "").strip()
        asset_role = row.get("asset_role", "").strip()
        status = row.get("status", "").strip()
        if not sku or not variant_id or not asset_role:
            errors.append("sku-media.csv: every row requires sku, variant_id, and asset_role")
            continue
        if sku not in known_skus:
            errors.append(f"sku-media.csv: unknown SKU reference: {sku}")
            continue
        if status not in ALLOWED_MEDIA_STATUSES:
            errors.append(f"sku-media.csv: invalid status for {sku}/{variant_id}/{asset_role}: {status}")
        media_keys.append((sku, variant_id, asset_role))
        if variant_id == "base":
            base_media_roles[sku].add(asset_role)
        if status != "verified":
            continue
        source_kind = row.get("source_kind", "").strip()
        captured_at = row.get("captured_at", "").strip()
        required_verified_fields = (
            "source_reference",
            "rights_evidence_reference",
            "captured_at",
            "sha256",
            "owner",
        )
        missing_verified = [field for field in required_verified_fields if not row.get(field, "").strip()]
        if source_kind not in ALLOWED_MEDIA_SOURCE_KINDS:
            errors.append(
                f"sku-media.csv: verified row {sku}/{variant_id}/{asset_role} requires "
                "source_kind sample_photo or supplier_authorized"
            )
        if missing_verified:
            errors.append(
                f"sku-media.csv: verified row {sku}/{variant_id}/{asset_role} is missing: "
                f"{', '.join(missing_verified)}"
            )
        if row.get("sha256", "").strip() and not SHA256.fullmatch(row["sha256"].strip()):
            errors.append(f"sku-media.csv: invalid sha256 for {sku}/{variant_id}/{asset_role}")
        if captured_at:
            try:
                parsed_at = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
            except ValueError:
                parsed_at = None
            if parsed_at is None or parsed_at.tzinfo is None:
                errors.append(
                    f"sku-media.csv: captured_at must be ISO-8601 with timezone for "
                    f"{sku}/{variant_id}/{asset_role}"
                )
    if len(media_keys) != len(set(media_keys)):
        errors.append("sku-media.csv: duplicate sku/variant_id/asset_role rows are forbidden")
    for sku in sorted(known_skus):
        missing_roles = sorted(REQUIRED_MEDIA_ROLES - base_media_roles[sku])
        if missing_roles:
            errors.append(f"sku-media.csv: {sku} base variant is missing roles: {', '.join(missing_roles)}")

    if not rows_by_file.get("finance-reconciliation.csv"):
        errors.append("finance-reconciliation.csv: at least one reconciliation row is required")

    submission_readiness = _submission_readiness(rows_by_file, known_skus)
    return {
        "contract": "kjds-startup-package-v4",
        "status": "structurally_valid" if not errors else "invalid",
        "directory": str(directory.resolve()),
        "files": files,
        "coverage": {
            "skus": sorted(known_skus),
            "suppliers_per_sku": {sku: len(suppliers_by_sku[sku]) for sku in sorted(known_skus)},
            "media_roles_per_sku": {sku: len(base_media_roles[sku]) for sku in sorted(known_skus)},
            "ozon_api_identities": len(identity_rows),
            "candidate_metrics_per_candidate": {
                candidate_ref: len({metric for ref, metric in candidate_keys if ref == candidate_ref})
                for candidate_ref in sorted(candidate_refs)
            },
        },
        "submission_readiness": submission_readiness,
        "formal_fact_promoted": False,
        "errors": errors,
        "warnings": [
            "Structural validation does not prove truth, evidence validity, domain readiness, or Gate approval."
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the KJDS startup CSV package structure.")
    parser.add_argument("directory", nargs="?", type=Path, default=Path("web/public/startup"))
    parser.add_argument(
        "--require-review-ready",
        action="store_true",
        help="Return exit code 3 unless every section has enough non-placeholder data for human evidence intake.",
    )
    args = parser.parse_args()
    report = validate_startup_package(args.directory)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "structurally_valid":
        return 2
    if args.require_review_ready and report["submission_readiness"]["status"] != "ready_for_human_intake":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

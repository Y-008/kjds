from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .domain import ChargeType
from .evidence import EvidenceGrade, EvidenceRecord, EvidenceService, parse_timestamp
from .finance import FeeMapping, FeeSignRule, FinanceService
from .imports import ImportDataRow, ImportResult, OzonImportService
from .ozon_contracts import OzonRecordType

FINANCE_RECORD_TYPES = {
    OzonRecordType.FEE.value,
    OzonRecordType.ACCRUAL.value,
    OzonRecordType.RETURN.value,
    OzonRecordType.SETTLEMENT.value,
}


class AccrualAccountingClass(StrEnum):
    SALES = "sales"
    DISCOUNT = "discount"
    PLATFORM_FEE = "platform_fee"
    LOGISTICS = "logistics"
    COMPENSATION = "compensation"
    OTHER_REVIEW = "other_review"


class AccrualExpectedSign(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    EITHER = "either"


class OzonFinanceReportReviewService:
    source = "ozon_finance_report_review"

    def __init__(self, *, engine, evidence: EvidenceService, imports: OzonImportService) -> None:
        self.engine = engine
        self.evidence = evidence
        self.imports = imports

    def review(
        self,
        *,
        import_id: str,
        accepted: bool,
        authentic_account_export: bool,
        period_matches: bool,
        not_public_sample: bool,
        complete_export: bool,
        rationale: str,
        reviewed_by: str,
    ) -> dict[str, Any]:
        rationale = rationale.strip()
        if not rationale:
            raise ValueError("Finance report review requires a rationale")
        imported, report = self._finance_import(import_id)
        report_period = self._report_period(report)
        if report.created_by == reviewed_by:
            raise ValueError("Finance report uploader cannot review their own report")

        checks = {
            "authentic_account_export": authentic_account_export,
            "period_matches": period_matches,
            "not_public_sample": not_public_sample,
            "complete_export": complete_export,
        }
        if accepted and not all(checks.values()):
            raise ValueError("Accepted finance report review requires all source checks to pass")
        decision = "accepted" if accepted else "rejected"
        payload = {
            "decision": decision,
            "rationale": rationale,
            "import_id": imported.id,
            "record_type": imported.record_type,
            "report_evidence_id": report.id,
            "report_sha256": report.sha256,
            "reviewed_by": reviewed_by,
            "submitted_by": report.created_by,
            **report_period,
            "checks": checks,
        }
        for prior in self._reviews(imported, report):
            if prior.created_by != reviewed_by:
                continue
            if all(prior.metadata.get(key) == value for key, value in payload.items()):
                return {"import": imported, "report": report, "review": prior, "idempotent": True}
            raise ValueError("Finance report review is immutable and cannot be overwritten")

        content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        review = self.evidence.capture(
            content=content,
            filename=f"{imported.id}-{reviewed_by}-finance-review.json",
            content_type="application/json",
            source=self.source,
            source_ref=f"ozon-import://{imported.id}/finance-review/{reviewed_by}",
            grade=EvidenceGrade.A,
            effective_at=datetime.now(UTC).isoformat(),
            effective_until=None,
            created_by=reviewed_by,
            metadata={"evidence_role": "review_attestation", "retention_class": "financial", **payload},
        )
        report_edge = self.evidence.link(
            evidence_id=review.id,
            target_type="evidence",
            target_id=report.id,
            relationship="reviews",
            created_by=reviewed_by,
        )
        import_edge = self.evidence.link(
            evidence_id=review.id,
            target_type="import_job",
            target_id=imported.id,
            relationship="finance_review_attestation",
            created_by=reviewed_by,
        )
        return {
            "import": imported,
            "report": report,
            "review": review,
            "lineage": [report_edge, import_edge],
            "idempotent": False,
        }

    def status(self, import_id: str) -> dict[str, Any]:
        imported, report = self._finance_import(import_id)
        status, reviews = self._decision_status(imported, report)
        return {
            "import_id": imported.id,
            "report_evidence_id": report.id,
            "record_type": imported.record_type,
            "status": status,
            "ready": status == "accepted",
            "review_count": len(reviews),
            "review_packet": self._review_packet(imported, report),
            **self._report_period(report),
        }

    def _review_packet(self, imported: ImportResult, report: EvidenceRecord) -> dict[str, Any]:
        """Return aggregate-only source facts needed by an independent reviewer."""
        with Session(self.engine) as session:
            rows = list(
                session.scalars(
                    select(ImportDataRow)
                    .where(ImportDataRow.import_id == imported.id)
                    .order_by(ImportDataRow.row_number)
                ).all()
            )
        accepted = [row for row in rows if not row.errors_json]
        currency_totals: dict[str, dict[str, Any]] = {}
        pair_totals: dict[tuple[str, str], dict[str, Any]] = {}
        effective_values: list[str] = []
        for row in accepted:
            normalized = row.normalized_json
            effective_at = normalized.get("effective_at")
            if isinstance(effective_at, str) and effective_at:
                effective_values.append(effective_at)
            currency = normalized.get("currency")
            amount = normalized.get("amount")
            if isinstance(currency, str) and currency and amount is not None:
                bucket = currency_totals.setdefault(
                    currency,
                    {"currency": currency, "row_count": 0, "total_amount": Decimal("0")},
                )
                bucket["row_count"] += 1
                bucket["total_amount"] += Decimal(str(amount))
            if imported.record_type == OzonRecordType.ACCRUAL.value:
                group = normalized.get("accrual_group")
                accrual_type = normalized.get("accrual_type")
                if isinstance(group, str) and group.strip() and isinstance(accrual_type, str) and accrual_type.strip():
                    pair = (group.strip(), accrual_type.strip())
                    bucket = pair_totals.setdefault(
                        pair,
                        {
                            "accrual_group": pair[0],
                            "accrual_type": pair[1],
                            "row_count": 0,
                            "currency_totals": {},
                        },
                    )
                    bucket["row_count"] += 1
                    if isinstance(currency, str) and currency and amount is not None:
                        totals = bucket["currency_totals"]
                        totals[currency] = totals.get(currency, Decimal("0")) + Decimal(str(amount))

        row_numbers = [row.row_number for row in rows]
        contiguous = not row_numbers or row_numbers == list(range(row_numbers[0], row_numbers[-1] + 1))
        return {
            "source": {
                "filename": report.filename,
                "sha256": report.sha256,
                "byte_size": report.byte_size,
                "content_type": report.content_type,
                "submitted_by": report.created_by,
                "recorded_at": self._utc_timestamp(report.recorded_at),
            },
            "import": {
                "filename": imported.filename,
                "sha256": imported.sha256,
                "status": imported.status,
                "row_count": imported.row_count,
                "accepted_count": imported.accepted_count,
                "rejected_count": imported.rejected_count,
                "mapped_fields": sorted(imported.mapping),
            },
            "integrity": {
                "evidence_valid": True,
                "sha256_matches_import": report.sha256 == imported.sha256,
                "source_lineage_verified": True,
                "row_numbers_contiguous": contiguous,
            },
            "aggregates": {
                "currency_totals": [
                    {
                        "currency": item["currency"],
                        "row_count": item["row_count"],
                        "total_amount": str(item["total_amount"]),
                    }
                    for item in sorted(currency_totals.values(), key=lambda item: item["currency"])
                ],
                "earliest_effective_at": min(effective_values) if effective_values else None,
                "latest_effective_at": max(effective_values) if effective_values else None,
                "accrual_pairs": [
                    {
                        "accrual_group": item["accrual_group"],
                        "accrual_type": item["accrual_type"],
                        "row_count": item["row_count"],
                        "currency_totals": [
                            {"currency": currency, "total_amount": str(total)}
                            for currency, total in sorted(item["currency_totals"].items())
                        ],
                    }
                    for item in sorted(
                        pair_totals.values(),
                        key=lambda item: (item["accrual_group"], item["accrual_type"]),
                    )
                ],
            },
            "boundaries": {
                "aggregate_only": True,
                "raw_rows_exposed": False,
                "automatic_acceptance": False,
                "automatic_classification": False,
                "automatic_finance_posting": False,
            },
        }

    def require_accepted(self, import_id: str) -> None:
        imported, report = self._finance_import(import_id)
        status, _ = self._decision_status(imported, report)
        if status != "accepted":
            raise ValueError("Finance import requires an independent accepted source review")

    def _decision_status(
        self, imported: ImportResult, report: EvidenceRecord
    ) -> tuple[str, list[EvidenceRecord]]:
        reviews = self._reviews(imported, report)
        decisions = {item.metadata["decision"] for item in reviews}
        status = "rejected" if "rejected" in decisions else "accepted" if "accepted" in decisions else "pending"
        return status, reviews

    def _finance_import(self, import_id: str) -> tuple[ImportResult, EvidenceRecord]:
        imported = self.imports.get(import_id)
        if imported.record_type not in FINANCE_RECORD_TYPES:
            raise ValueError("Import is not an Ozon finance report")
        if not imported.evidence_id:
            raise ValueError("Finance import has no immutable source evidence")
        source_ids = self.evidence.target_evidence_ids(
            target_type="import_job", target_id=imported.id, relationship="source_for"
        )
        if source_ids != [imported.evidence_id]:
            raise ValueError("Finance import source lineage is missing or ambiguous")
        self.evidence.require_valid([imported.evidence_id])
        report = self.evidence.get(imported.evidence_id)
        if (
            report.source != "ozon_export"
            or report.sha256 != imported.sha256
            or report.metadata.get("sha256") != imported.sha256
        ):
            raise ValueError("Finance import source evidence does not match the imported report")
        return imported, report

    @staticmethod
    def _report_period(report: EvidenceRecord) -> dict[str, str]:
        start_value = report.metadata.get("report_period_start")
        end_value = report.metadata.get("report_period_end")
        if not isinstance(start_value, str) or not isinstance(end_value, str):
            raise ValueError("Finance report has no immutable expected report period")
        try:
            start = date.fromisoformat(start_value)
            end = date.fromisoformat(end_value)
        except ValueError as exc:
            raise ValueError("Finance report expected period must use YYYY-MM-DD") from exc
        if end < start or (end - start).days > 30:
            raise ValueError("Finance report expected period must be ordered and no longer than 31 days")
        return {"report_period_start": start.isoformat(), "report_period_end": end.isoformat()}

    @staticmethod
    def _utc_timestamp(value: str) -> str:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return (parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)).isoformat()

    def _reviews(self, imported: ImportResult, report: EvidenceRecord) -> list[EvidenceRecord]:
        import_review_ids = set(
            self.evidence.target_evidence_ids(
                target_type="import_job",
                target_id=imported.id,
                relationship="finance_review_attestation",
            )
        )
        report_review_ids = self.evidence.target_evidence_ids(
            target_type="evidence", target_id=report.id, relationship="reviews"
        )
        reviews: list[EvidenceRecord] = []
        for review_id in report_review_ids:
            if review_id not in import_review_ids:
                continue
            try:
                self.evidence.require_valid([review_id])
                review = self.evidence.get(review_id)
            except (KeyError, RuntimeError, ValueError):
                continue
            metadata = review.metadata
            checks = metadata.get("checks")
            if (
                review.source == self.source
                and metadata.get("evidence_role") == "review_attestation"
                and metadata.get("import_id") == imported.id
                and metadata.get("record_type") == imported.record_type
                and metadata.get("report_evidence_id") == report.id
                and metadata.get("report_sha256") == report.sha256
                and metadata.get("submitted_by") == report.created_by
                and metadata.get("report_period_start") == report.metadata.get("report_period_start")
                and metadata.get("report_period_end") == report.metadata.get("report_period_end")
                and metadata.get("reviewed_by") == review.created_by
                and review.created_by != report.created_by
                and metadata.get("decision") in {"accepted", "rejected"}
                and isinstance(metadata.get("rationale"), str)
                and metadata["rationale"].strip()
                and isinstance(checks, dict)
                and set(checks) == {
                    "authentic_account_export",
                    "period_matches",
                    "not_public_sample",
                    "complete_export",
                }
                and all(isinstance(value, bool) for value in checks.values())
                and (metadata["decision"] != "accepted" or all(checks.values()))
            ):
                reviews.append(review)
        return reviews


class OzonFeeMappingApprovalService:
    source = "ozon_fee_mapping_approval"

    def __init__(
        self,
        *,
        engine,
        evidence: EvidenceService,
        imports: OzonImportService,
        reviews: OzonFinanceReportReviewService,
        finance: FinanceService,
    ) -> None:
        self.engine = engine
        self.evidence = evidence
        self.imports = imports
        self.reviews = reviews
        self.finance = finance

    def status(self, import_id: str) -> dict[str, Any]:
        imported, _, rows = self._accepted_fee_rows(import_id)
        grouped: dict[str, list[str]] = defaultdict(list)
        for row in rows:
            grouped[str(row.normalized_json["fee_type"])].append(str(row.normalized_json["effective_at"]))

        codes = []
        for raw_code, effective_values in sorted(grouped.items()):
            mappings = [
                self.finance.resolve_fee_mapping(provider="ozon", raw_code=raw_code, effective_at=value)
                for value in effective_values
            ]
            valid = [mapping for mapping in mappings if mapping is not None and self._valid_approval(mapping)]
            codes.append(
                {
                    "raw_code": raw_code,
                    "row_count": len(effective_values),
                    "earliest_effective_at": min(effective_values),
                    "latest_effective_at": max(effective_values),
                    "ready": len(valid) == len(effective_values),
                    "mapping_ids": sorted({mapping.id for mapping in valid}),
                }
            )
        return {
            "import_id": imported.id,
            "record_type": imported.record_type,
            "ready": bool(codes) and all(item["ready"] for item in codes),
            "codes": codes,
        }

    def approve(
        self,
        *,
        import_id: str,
        raw_code: str,
        canonical_type: ChargeType,
        sign_rule: FeeSignRule,
        effective_from: str,
        effective_until: str | None,
        rationale: str,
        approved_by: str,
    ) -> dict[str, Any]:
        raw_code = raw_code.strip()
        rationale = rationale.strip()
        approved_by = approved_by.strip()
        if not raw_code or not rationale or not approved_by:
            raise ValueError("Fee mapping approval requires raw code, rationale, and approver")
        imported, report, rows = self._accepted_fee_rows(import_id)
        if report.created_by == approved_by:
            raise ValueError("Finance report uploader cannot approve fee mappings from their own report")
        observed_codes = {str(row.normalized_json["fee_type"]) for row in rows}
        if raw_code not in observed_codes:
            raise ValueError("Fee mapping raw code was not observed in the accepted import")

        start = self._normalized_timestamp(effective_from, "effective_from")
        end = self._normalized_timestamp(effective_until, "effective_until") if effective_until else None
        if end is not None and datetime.fromisoformat(end) <= datetime.fromisoformat(start):
            raise ValueError("effective_until must be later than effective_from")
        payload = {
            "provider": "ozon",
            "import_id": imported.id,
            "report_evidence_id": report.id,
            "report_sha256": report.sha256,
            "raw_code": raw_code,
            "canonical_type": canonical_type.value,
            "sign_rule": sign_rule.value,
            "effective_from": start,
            "effective_until": end,
            "rationale": rationale,
            "approved_by": approved_by,
            "submitted_by": report.created_by,
        }
        content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        approval = self.evidence.capture(
            content=content,
            filename=f"{imported.id}-fee-mapping-approval.json",
            content_type="application/json",
            source=self.source,
            source_ref=f"ozon-import://{imported.id}/fee-mapping/{approved_by}",
            grade=EvidenceGrade.A,
            effective_at=start,
            effective_until=end,
            created_by=approved_by,
            metadata={"evidence_role": "fee_mapping_approval", "retention_class": "financial", **payload},
        )
        self.evidence.link(
            evidence_id=approval.id,
            target_type="evidence",
            target_id=report.id,
            relationship="supports_fee_mapping",
            created_by=approved_by,
        )
        self.evidence.link(
            evidence_id=approval.id,
            target_type="import_job",
            target_id=imported.id,
            relationship="fee_mapping_approval",
            created_by=approved_by,
        )
        mapping = self.finance.register_fee_mapping(
            provider="ozon",
            raw_code=raw_code,
            canonical_type=canonical_type,
            sign_rule=sign_rule,
            effective_from=start,
            effective_until=end,
            evidence_id=approval.id,
            approved_by=approved_by,
        )
        mapping_edge = self.evidence.link(
            evidence_id=approval.id,
            target_type="fee_mapping",
            target_id=mapping.id,
            relationship="approval_for",
            created_by=approved_by,
        )
        return {"mapping": mapping, "approval": approval, "lineage": [mapping_edge]}

    def require_mapped(self, import_id: str) -> None:
        status = self.status(import_id)
        missing = [item["raw_code"] for item in status["codes"] if not item["ready"]]
        if not status["codes"] or missing:
            detail = ", ".join(missing) if missing else "no accepted fee rows"
            raise ValueError(f"Ozon fee import requires approved fee mappings: {detail}")

    def _accepted_fee_rows(self, import_id: str) -> tuple[ImportResult, EvidenceRecord, list[ImportDataRow]]:
        self.reviews.require_accepted(import_id)
        imported, report = self.reviews._finance_import(import_id)
        if imported.record_type != OzonRecordType.FEE.value:
            raise ValueError("Import is not an Ozon fee report")
        with Session(self.engine) as session:
            rows = list(
                session.scalars(
                    select(ImportDataRow)
                    .where(ImportDataRow.import_id == import_id)
                    .order_by(ImportDataRow.row_number)
                ).all()
            )
        accepted = [
            row
            for row in rows
            if not row.errors_json
            and row.normalized_json.get("fee_type")
            and row.normalized_json.get("effective_at")
        ]
        return imported, report, accepted

    def _valid_approval(self, mapping: FeeMapping) -> bool:
        try:
            self.evidence.require_valid([mapping.evidence_id])
            approval = self.evidence.get(mapping.evidence_id)
        except (KeyError, RuntimeError, ValueError):
            return False
        metadata = approval.metadata
        if not (
            approval.source == self.source
            and metadata.get("evidence_role") == "fee_mapping_approval"
            and metadata.get("provider") == "ozon"
            and metadata.get("raw_code") == mapping.raw_code
            and metadata.get("canonical_type") == mapping.canonical_type
            and metadata.get("sign_rule") == mapping.sign_rule
            and self._same_timestamp(metadata.get("effective_from"), mapping.effective_from)
            and self._same_timestamp(metadata.get("effective_until"), mapping.effective_until)
            and metadata.get("approved_by") == mapping.approved_by == approval.created_by
            and metadata.get("submitted_by") != approval.created_by
        ):
            return False
        import_id = metadata.get("import_id")
        report_evidence_id = metadata.get("report_evidence_id")
        if not isinstance(import_id, str) or not isinstance(report_evidence_id, str):
            return False
        try:
            self.reviews.require_accepted(import_id)
            imported, report = self.reviews._finance_import(import_id)
        except (KeyError, RuntimeError, ValueError):
            return False
        return (
            imported.record_type == OzonRecordType.FEE.value
            and report.id == report_evidence_id
            and report.sha256 == metadata.get("report_sha256")
            and self.evidence.target_evidence_ids(
                target_type="fee_mapping", target_id=mapping.id, relationship="approval_for"
            )
            == [approval.id]
            and self.evidence.target_evidence_ids(
                target_type="evidence", target_id=report.id, relationship="supports_fee_mapping"
            )
            == [approval.id]
            and self.evidence.target_evidence_ids(
                target_type="import_job", target_id=imported.id, relationship="fee_mapping_approval"
            )
            == [approval.id]
        )

    @staticmethod
    def _normalized_timestamp(value: str, field: str) -> str:
        return parse_timestamp(value, field).isoformat()

    @staticmethod
    def _same_timestamp(left: Any, right: Any) -> bool:
        if left is None or right is None:
            return left is right

        def utc(value: Any) -> datetime:
            parsed = datetime.fromisoformat(str(value))
            return (parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed).astimezone(UTC)

        try:
            return utc(left) == utc(right)
        except ValueError:
            return False


class OzonAccrualClassificationService:
    """Classifies platform accrual control rows without posting finance entries."""

    source = "ozon_accrual_classification_approval"
    posting_policy = "control_only_no_finance_entry"

    def __init__(
        self,
        *,
        engine,
        evidence: EvidenceService,
        imports: OzonImportService,
        reviews: OzonFinanceReportReviewService,
    ) -> None:
        self.engine = engine
        self.evidence = evidence
        self.imports = imports
        self.reviews = reviews

    def status(self, import_id: str) -> dict[str, Any]:
        imported, report, rows = self._accepted_accrual_rows(import_id)
        approvals = self._valid_approvals(imported, report)
        grouped: dict[tuple[str, str], list[ImportDataRow]] = defaultdict(list)
        for row in rows:
            grouped[self._pair(row.normalized_json)].append(row)

        pairs: list[dict[str, Any]] = []
        for (accrual_group, accrual_type), pair_rows in sorted(grouped.items()):
            resolved = [
                self._resolve(
                    approvals,
                    accrual_group,
                    accrual_type,
                    str(row.normalized_json["effective_at"]),
                    Decimal(str(row.normalized_json["amount"])),
                )
                for row in pair_rows
            ]
            valid = [item for item in resolved if item is not None]
            currency_totals = self._currency_totals(pair_rows)
            currency = self._single_currency(pair_rows)
            pairs.append(
                {
                    "accrual_group": accrual_group,
                    "accrual_type": accrual_type,
                    "row_count": len(pair_rows),
                    "total_amount": currency_totals[0]["total_amount"] if currency else None,
                    "currency": currency,
                    "currency_totals": currency_totals,
                    "observed_signs": sorted(
                        {self._amount_sign(Decimal(str(row.normalized_json["amount"]))) for row in pair_rows}
                    ),
                    "earliest_effective_at": min(str(row.normalized_json["effective_at"]) for row in pair_rows),
                    "latest_effective_at": max(str(row.normalized_json["effective_at"]) for row in pair_rows),
                    "ready": len(valid) == len(pair_rows),
                    "approval_ids": sorted({item.id for item in valid}),
                    "accounting_classes": sorted(
                        {str(item.metadata["accounting_class"]) for item in valid}
                    ),
                    "expected_signs": sorted({str(item.metadata["expected_sign"]) for item in valid}),
                }
            )
        return {
            "import_id": imported.id,
            "record_type": imported.record_type,
            "ready": bool(pairs) and all(item["ready"] for item in pairs),
            "posting_policy": self.posting_policy,
            "automatic_finance_posting": False,
            "order_revenue_replacement": False,
            "pairs": pairs,
        }

    def approve(
        self,
        *,
        import_id: str,
        accrual_group: str,
        accrual_type: str,
        accounting_class: AccrualAccountingClass,
        expected_sign: AccrualExpectedSign,
        effective_from: str,
        effective_until: str | None,
        rationale: str,
        approved_by: str,
    ) -> dict[str, Any]:
        accrual_group = accrual_group.strip()
        accrual_type = accrual_type.strip()
        rationale = rationale.strip()
        approved_by = approved_by.strip()
        if not all((accrual_group, accrual_type, rationale, approved_by)):
            raise ValueError("Accrual classification requires group, type, rationale, and approver")
        imported, report, rows = self._accepted_accrual_rows(import_id)
        if report.created_by == approved_by:
            raise ValueError("Finance report uploader cannot approve accrual classifications from their own report")
        observed = {self._pair(row.normalized_json) for row in rows}
        pair = (accrual_group, accrual_type)
        if pair not in observed:
            raise ValueError("Accrual group and type were not observed in the accepted import")

        start = parse_timestamp(effective_from, "effective_from")
        end = parse_timestamp(effective_until, "effective_until") if effective_until else None
        if end is not None and end <= start:
            raise ValueError("effective_until must be later than effective_from")
        covered_rows = [
            row
            for row in rows
            if self._pair(row.normalized_json) == pair
            and (value := parse_timestamp(str(row.normalized_json["effective_at"]), "effective_at")) >= start
            and (end is None or value < end)
        ]
        if not covered_rows:
            raise ValueError("Accrual classification effective interval does not cover an observed row")
        if any(
            not self._sign_matches(Decimal(str(row.normalized_json["amount"])), expected_sign)
            for row in covered_rows
        ):
            raise ValueError("Accrual classification expected sign does not match every covered row")

        prior = self._valid_approvals(imported, report)
        stable = {
            "provider": "ozon",
            "import_id": imported.id,
            "report_evidence_id": report.id,
            "report_sha256": report.sha256,
            "accrual_group": accrual_group,
            "accrual_type": accrual_type,
            "accounting_class": accounting_class.value,
            "expected_sign": expected_sign.value,
            "effective_from": start.isoformat(),
            "effective_until": end.isoformat() if end else None,
            "posting_policy": self.posting_policy,
            "automatic_finance_posting": False,
            "order_revenue_replacement": False,
            "rationale": rationale,
            "approved_by": approved_by,
            "submitted_by": report.created_by,
        }
        for item in prior:
            if all(item.metadata.get(key) == value for key, value in stable.items()):
                return {"approval": item, "idempotent": True}
        version = 1 + max(
            (
                int(item.metadata["version"])
                for item in prior
                if item.metadata.get("accrual_group") == accrual_group
                and item.metadata.get("accrual_type") == accrual_type
            ),
            default=0,
        )
        payload = {**stable, "version": version}
        content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        approval = self.evidence.capture(
            content=content,
            filename=f"{imported.id}-accrual-classification-v{version}.json",
            content_type="application/json",
            source=self.source,
            source_ref=f"ozon-import://{imported.id}/accrual-classification/{approved_by}/v{version}",
            grade=EvidenceGrade.A,
            effective_at=start.isoformat(),
            effective_until=end.isoformat() if end else None,
            created_by=approved_by,
            metadata={"evidence_role": "accrual_classification_approval", "retention_class": "financial", **payload},
        )
        report_edge = self.evidence.link(
            evidence_id=approval.id,
            target_type="evidence",
            target_id=report.id,
            relationship="supports_accrual_classification",
            created_by=approved_by,
        )
        import_edge = self.evidence.link(
            evidence_id=approval.id,
            target_type="import_job",
            target_id=imported.id,
            relationship="accrual_classification_approval",
            created_by=approved_by,
        )
        return {"approval": approval, "lineage": [report_edge, import_edge], "idempotent": False}

    def require_classified(self, import_id: str) -> None:
        status = self.status(import_id)
        missing = [f'{item["accrual_group"]} / {item["accrual_type"]}' for item in status["pairs"] if not item["ready"]]
        if not status["pairs"] or missing:
            detail = ", ".join(missing) if missing else "no accepted accrual rows"
            raise ValueError(f"Ozon accrual import requires approved control classifications: {detail}")

    def _accepted_accrual_rows(self, import_id: str) -> tuple[ImportResult, EvidenceRecord, list[ImportDataRow]]:
        self.reviews.require_accepted(import_id)
        imported, report = self.reviews._finance_import(import_id)
        if imported.record_type != OzonRecordType.ACCRUAL.value:
            raise ValueError("Import is not an Ozon accrual report")
        with Session(self.engine) as session:
            rows = list(
                session.scalars(
                    select(ImportDataRow)
                    .where(ImportDataRow.import_id == import_id)
                    .order_by(ImportDataRow.row_number)
                ).all()
            )
        accepted = [
            row
            for row in rows
            if not row.errors_json
            and row.normalized_json.get("accrual_group")
            and row.normalized_json.get("accrual_type")
            and row.normalized_json.get("amount") is not None
            and row.normalized_json.get("currency")
            and row.normalized_json.get("effective_at")
        ]
        return imported, report, accepted

    def _valid_approvals(self, imported: ImportResult, report: EvidenceRecord) -> list[EvidenceRecord]:
        import_ids = set(
            self.evidence.target_evidence_ids(
                target_type="import_job",
                target_id=imported.id,
                relationship="accrual_classification_approval",
            )
        )
        report_ids = self.evidence.target_evidence_ids(
            target_type="evidence",
            target_id=report.id,
            relationship="supports_accrual_classification",
        )
        approvals: list[EvidenceRecord] = []
        for approval_id in report_ids:
            if approval_id not in import_ids:
                continue
            try:
                self.evidence.require_valid([approval_id])
                approval = self.evidence.get(approval_id)
                metadata = approval.metadata
                AccrualAccountingClass(str(metadata.get("accounting_class")))
                AccrualExpectedSign(str(metadata.get("expected_sign")))
                start = parse_timestamp(str(metadata.get("effective_from")), "effective_from")
                end_value = metadata.get("effective_until")
                end = parse_timestamp(str(end_value), "effective_until") if end_value else None
            except (KeyError, RuntimeError, TypeError, ValueError):
                continue
            if (
                approval.source == self.source
                and metadata.get("evidence_role") == "accrual_classification_approval"
                and metadata.get("provider") == "ozon"
                and metadata.get("import_id") == imported.id
                and metadata.get("report_evidence_id") == report.id
                and metadata.get("report_sha256") == report.sha256
                and metadata.get("submitted_by") == report.created_by
                and metadata.get("approved_by") == approval.created_by
                and approval.created_by != report.created_by
                and isinstance(metadata.get("accrual_group"), str)
                and metadata["accrual_group"].strip()
                and isinstance(metadata.get("accrual_type"), str)
                and metadata["accrual_type"].strip()
                and isinstance(metadata.get("version"), int)
                and metadata["version"] > 0
                and metadata.get("posting_policy") == self.posting_policy
                and metadata.get("automatic_finance_posting") is False
                and metadata.get("order_revenue_replacement") is False
                and isinstance(metadata.get("rationale"), str)
                and metadata["rationale"].strip()
                and self._same_instant(approval.effective_at, start)
                and (
                    (approval.effective_until is None and end is None)
                    or (
                        approval.effective_until is not None
                        and end is not None
                        and self._same_instant(approval.effective_until, end)
                    )
                )
            ):
                approvals.append(approval)
        return approvals

    @staticmethod
    def _resolve(
        approvals: list[EvidenceRecord],
        accrual_group: str,
        accrual_type: str,
        effective_at: str,
        amount: Decimal,
    ) -> EvidenceRecord | None:
        effective = parse_timestamp(effective_at, "effective_at")
        candidates = []
        for item in approvals:
            metadata = item.metadata
            if metadata["accrual_group"] != accrual_group or metadata["accrual_type"] != accrual_type:
                continue
            start = parse_timestamp(str(metadata["effective_from"]), "effective_from")
            end_value = metadata.get("effective_until")
            end = parse_timestamp(str(end_value), "effective_until") if end_value else None
            expected_sign = AccrualExpectedSign(str(metadata["expected_sign"]))
            if effective >= start and (end is None or effective < end) and OzonAccrualClassificationService._sign_matches(
                amount, expected_sign
            ):
                candidates.append(item)
        return max(candidates, key=lambda item: int(item.metadata["version"]), default=None)

    @staticmethod
    def _pair(values: dict[str, Any]) -> tuple[str, str]:
        return str(values["accrual_group"]).strip(), str(values["accrual_type"]).strip()

    @staticmethod
    def _single_currency(rows: list[ImportDataRow]) -> str | None:
        values = {str(row.normalized_json["currency"]) for row in rows}
        return next(iter(values)) if len(values) == 1 else None

    @staticmethod
    def _currency_totals(rows: list[ImportDataRow]) -> list[dict[str, str]]:
        totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for row in rows:
            totals[str(row.normalized_json["currency"])] += Decimal(str(row.normalized_json["amount"]))
        return [
            {"currency": currency, "total_amount": str(total)}
            for currency, total in sorted(totals.items())
        ]

    @staticmethod
    def _amount_sign(amount: Decimal) -> str:
        return "positive" if amount > 0 else "negative" if amount < 0 else "zero"

    @staticmethod
    def _sign_matches(amount: Decimal, expected: AccrualExpectedSign) -> bool:
        return expected == AccrualExpectedSign.EITHER or OzonAccrualClassificationService._amount_sign(amount) == expected.value

    @staticmethod
    def _same_instant(left: str, right: datetime) -> bool:
        parsed = datetime.fromisoformat(left)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC) == right.astimezone(UTC)

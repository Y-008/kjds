from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from .evidence import EvidenceGrade, EvidenceRecord, EvidenceService


class DemandReportGateService:
    requirement_id = "SKU-000"
    minimum_window_days = 28
    research_source_systems = {
        "ozon_data",
        "ozon_seller_analytics",
        "ozon_category_analytics",
        "ozon_trends",
        "ozon_what_to_sell",
        "ozon_search_terms",
        "ozon_competitor_compare",
        "sanitized_history",
        "fixed_test_data",
    }
    composable_real_execution_sources = {
        "ozon_category_analytics",
        "ozon_trends",
        "ozon_what_to_sell",
        "ozon_competitor_compare",
    }
    supported_source_systems = research_source_systems

    def __init__(self, *, evidence: EvidenceService) -> None:
        self.evidence = evidence

    def capture_report(
        self,
        *,
        content: bytes,
        filename: str,
        content_type: str,
        effective_at: str,
        report_window_days: int,
        created_by: str,
        source_system: str = "ozon_data",
        source_locator: str | None = None,
    ) -> dict[str, Any]:
        source_system = source_system.strip().lower()
        if source_system not in self.supported_source_systems:
            raise ValueError("Unsupported SKU-000 demand evidence source system")
        if report_window_days < self.minimum_window_days:
            raise ValueError(
                f"SKU-000 requires at least {self.minimum_window_days} report days"
            )
        digest = hashlib.sha256(content).hexdigest()
        record = self.evidence.capture(
            content=content,
            filename=filename,
            content_type=content_type,
            source="gate_requirement",
            source_ref=f"gate://{self.requirement_id}/report/sha256/{digest}",
            grade=EvidenceGrade.A,
            effective_at=effective_at,
            effective_until=None,
            created_by=created_by,
            metadata={
                "requirement_id": self.requirement_id,
                "evidence_role": "source_report",
                "source_system": source_system,
                "source_locator": source_locator.strip() if source_locator else None,
                "report_window_days": report_window_days,
                "eligible_scopes": self._eligible_scopes(source_system),
                "fact_status": "research_signal",
                "cost_status": "estimate",
                "external_side_effect_allowed": False,
            },
        )
        edge = self.evidence.link(
            evidence_id=record.id,
            target_type="gate_requirement",
            target_id=self.requirement_id,
            relationship="source_report",
            created_by=created_by,
        )
        return {"evidence": record, "lineage": edge, "review_status": "pending"}

    def review(
        self,
        *,
        report_evidence_id: str,
        accepted: bool,
        rationale: str,
        reviewed_by: str,
    ) -> dict[str, Any]:
        rationale = rationale.strip()
        if not rationale:
            raise ValueError("Demand report review requires a rationale")
        report = self._source_report(report_evidence_id)
        if report.created_by == reviewed_by:
            raise ValueError("Demand report uploader cannot review their own report")

        decision = "accepted" if accepted else "rejected"
        existing = self._reviews_for_report(report)
        reviewer_records = [item for item in existing if item.created_by == reviewed_by]
        if reviewer_records:
            prior = reviewer_records[0]
            if (
                prior.metadata.get("decision") == decision
                and prior.metadata.get("rationale") == rationale
            ):
                return {"report": report, "review": prior, "idempotent": True}
            raise ValueError("Demand report review is immutable and cannot be overwritten")

        payload = {
            "decision": decision,
            "rationale": rationale,
            "report_evidence_id": report.id,
            "report_sha256": report.sha256,
            "reviewed_by": reviewed_by,
            "submitted_by": report.created_by,
            "source_system": report.metadata["source_system"],
            "eligible_scopes": self._eligible_scopes(report.metadata["source_system"]),
        }
        content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        review = self.evidence.capture(
            content=content,
            filename=f"{self.requirement_id}-{report.id}-review.json",
            content_type="application/json",
            source="gate_requirement_review",
            source_ref=f"gate://{self.requirement_id}/review/{report.id}/{reviewed_by}",
            grade=EvidenceGrade.A,
            effective_at=datetime.now(UTC).isoformat(),
            effective_until=None,
            created_by=reviewed_by,
            metadata={
                "requirement_id": self.requirement_id,
                "evidence_role": "review_attestation",
                **payload,
            },
        )
        report_edge = self.evidence.link(
            evidence_id=review.id,
            target_type="evidence",
            target_id=report.id,
            relationship="reviews",
            created_by=reviewed_by,
        )
        gate_edge = self.evidence.link(
            evidence_id=review.id,
            target_type="gate_requirement",
            target_id=self.requirement_id,
            relationship="review_attestation",
            created_by=reviewed_by,
        )
        return {
            "report": report,
            "review": review,
            "lineage": [report_edge, gate_edge],
            "idempotent": False,
        }

    def status(self) -> dict[str, Any]:
        accepted_report_ids: list[str] = []
        pending_report_ids: list[str] = []
        rejected_report_ids: list[str] = []
        invalid_report_ids: list[str] = []
        accepted_reports: list[EvidenceRecord] = []
        accepted_review_ids_by_report: dict[str, list[str]] = {}
        report_ids = self.evidence.target_evidence_ids(
            target_type="gate_requirement",
            target_id=self.requirement_id,
            relationship="source_report",
        )
        for report_id in report_ids:
            try:
                report = self._source_report(report_id)
            except (KeyError, TypeError, ValueError):
                invalid_report_ids.append(report_id)
                continue
            reviews = self._reviews_for_report(report)
            decisions = {item.metadata["decision"] for item in reviews}
            if "rejected" in decisions:
                rejected_report_ids.append(report.id)
            elif "accepted" in decisions:
                accepted_report_ids.append(report.id)
                accepted_reports.append(report)
                accepted_review_ids_by_report[report.id] = sorted(
                    item.id
                    for item in reviews
                    if item.metadata["decision"] == "accepted"
                )
            else:
                pending_report_ids.append(report.id)
        research_report_ids = [
            report.id
            for report in accepted_reports
            if "research" in self._eligible_scopes(report.metadata["source_system"])
        ]
        real_execution_report_ids = [
            report.id
            for report in accepted_reports
            if "real_execution" in self._eligible_scopes(report.metadata["source_system"])
        ]
        real_source_systems = sorted(
            {
                report.metadata["source_system"]
                for report in accepted_reports
                if report.metadata["source_system"] in self.composable_real_execution_sources
            }
        )
        ozon_data_ids = [
            report.id
            for report in accepted_reports
            if report.metadata["source_system"] == "ozon_data"
        ]
        real_execution_ready = bool(ozon_data_ids) or len(real_source_systems) >= 2
        research_evidence_ids = sorted(
            {
                evidence_id
                for report_id in research_report_ids
                for evidence_id in [
                    report_id,
                    *accepted_review_ids_by_report.get(report_id, []),
                ]
            }
        )
        real_execution_evidence_ids = sorted(
            {
                evidence_id
                for report_id in real_execution_report_ids
                for evidence_id in [
                    report_id,
                    *accepted_review_ids_by_report.get(report_id, []),
                ]
            }
        )
        research = {
            "ready": bool(research_report_ids),
            "accepted_report_ids": research_report_ids,
            "evidence_ids": research_evidence_ids,
            "blocking_reasons": [] if research_report_ids else ["RESEARCH_EVIDENCE_REQUIRED"],
        }
        real_execution = {
            "ready": real_execution_ready,
            "accepted_report_ids": real_execution_report_ids,
            "evidence_ids": real_execution_evidence_ids,
            "ozon_data_report_ids": ozon_data_ids,
            "independent_official_source_systems": real_source_systems,
            "blocking_reasons": []
            if real_execution_ready
            else ["REAL_EXECUTION_DEMAND_EVIDENCE_REQUIRED"],
        }
        return {
            "ready": real_execution_ready,
            "research_ready": research["ready"],
            "real_execution_ready": real_execution["ready"],
            "readiness": {
                "research": research,
                "real_execution": real_execution,
            },
            "accepted_report_ids": accepted_report_ids,
            "pending_report_ids": pending_report_ids,
            "rejected_report_ids": rejected_report_ids,
            "invalid_report_ids": invalid_report_ids,
            "source_report_count": len(report_ids),
        }

    def require_accepted(self, report_evidence_id: str, *, scope: str = "real_execution") -> None:
        if scope not in {"research", "real_execution"}:
            raise ValueError("Unsupported demand evidence decision scope")
        report = self._source_report(report_evidence_id.strip())
        decisions = {item.metadata["decision"] for item in self._reviews_for_report(report)}
        if "rejected" in decisions or "accepted" not in decisions:
            raise ValueError("Demand report is not currently accepted")
        if scope not in self._eligible_scopes(report.metadata["source_system"]):
            raise ValueError(f"Demand report is not eligible for {scope}")
        if scope == "real_execution" and not self.status()["real_execution_ready"]:
            raise ValueError("Demand evidence portfolio is not ready for real_execution")

    def _source_report(self, evidence_id: str) -> EvidenceRecord:
        linked_ids = self.evidence.target_evidence_ids(
            target_type="gate_requirement",
            target_id=self.requirement_id,
            relationship="source_report",
        )
        if evidence_id not in linked_ids:
            raise ValueError("Evidence is not a SKU-000 source report")
        self.evidence.require_valid([evidence_id])
        report = self.evidence.get(evidence_id)
        try:
            report_window_days = int(report.metadata.get("report_window_days", 0))
        except (TypeError, ValueError) as exc:
            raise ValueError("Demand report window is invalid") from exc
        if (
            report.source != "gate_requirement"
            or report.metadata.get("requirement_id") != self.requirement_id
            or report.metadata.get("evidence_role") != "source_report"
            or report.metadata.get("source_system") not in self.supported_source_systems
            or report_window_days < self.minimum_window_days
        ):
            raise ValueError("Evidence does not satisfy the SKU-000 source report contract")
        return report

    def _eligible_scopes(self, source_system: str) -> list[str]:
        scopes = ["research"]
        if source_system == "ozon_data" or source_system in self.composable_real_execution_sources:
            scopes.append("real_execution")
        return scopes

    def _reviews_for_report(self, report: EvidenceRecord) -> list[EvidenceRecord]:
        gate_attestation_ids = set(
            self.evidence.target_evidence_ids(
                target_type="gate_requirement",
                target_id=self.requirement_id,
                relationship="review_attestation",
            )
        )
        review_ids = self.evidence.target_evidence_ids(
            target_type="evidence",
            target_id=report.id,
            relationship="reviews",
        )
        reviews: list[EvidenceRecord] = []
        for review_id in review_ids:
            try:
                self.evidence.require_valid([review_id])
                review = self.evidence.get(review_id)
            except (KeyError, ValueError):
                continue
            metadata = review.metadata
            if (
                review.id in gate_attestation_ids
                and review.source == "gate_requirement_review"
                and metadata.get("requirement_id") == self.requirement_id
                and metadata.get("evidence_role") == "review_attestation"
                and metadata.get("report_evidence_id") == report.id
                and metadata.get("report_sha256") == report.sha256
                and metadata.get("submitted_by") == report.created_by
                and metadata.get("reviewed_by") == review.created_by
                and review.created_by != report.created_by
                and metadata.get("decision") in {"accepted", "rejected"}
                and isinstance(metadata.get("rationale"), str)
                and metadata["rationale"].strip()
            ):
                reviews.append(review)
        return reviews

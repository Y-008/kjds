from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from .evidence import (
    CLOSED_LOOP_RESERVED_SOURCES,
    EvidenceGrade,
    EvidenceIntegrityFinding,
    EvidenceService,
)
from .incident_recovery import IncidentRecoveryService


class EvidenceIntegrityMonitorService:
    """Turn bounded evidence verification failures into auditable incidents."""

    REPORT_SOURCE = "evidence-integrity-monitor"

    def __init__(self, *, evidence: EvidenceService, incidents: IncidentRecoveryService) -> None:
        self.evidence = evidence
        self.incidents = incidents

    def scan(
        self,
        *,
        actor_id: str,
        limit: int = 500,
        offset: int = 0,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        actor_id = actor_id.strip()
        if not actor_id:
            raise ValueError("Evidence integrity monitor identity is required")
        scanned_at = self._datetime(as_of) if as_of else datetime.now(UTC)
        result = self.evidence.scan_integrity(
            limit=limit,
            offset=offset,
            excluded_sources=(
                self.REPORT_SOURCE,
                *sorted(CLOSED_LOOP_RESERVED_SOURCES),
            ),
        )
        incident_ids: dict[str, str] = {}
        finding_evidence_ids: dict[str, str] = {}
        for finding in result.findings:
            fingerprint = self._fingerprint(finding)
            fingerprint_marker = f"integrity_fingerprint:{fingerprint}"
            report = self._finding_report(
                finding,
                fingerprint=fingerprint,
                scanned_at=scanned_at,
                actor_id=actor_id,
            )
            prior = [
                item
                for item in self.incidents.list()
                if item["trigger_type"] == "evidence_integrity_failed"
                and item["source_type"] == "evidence"
                and item["source_id"] == finding.evidence_id
                and fingerprint_marker in item["impact"]
            ]
            incident = next((item for item in prior if item["status"] != "closed"), None)
            if incident is None:
                generation = sum(item["status"] == "closed" for item in prior)
                incident = self.incidents.open(
                    idempotency_key=f"evidence-integrity:{fingerprint}:{generation}",
                    mode="live",
                    severity="medium",
                    trigger_type="evidence_integrity_failed",
                    source_type="evidence",
                    source_id=finding.evidence_id,
                    summary="Evidence integrity verification failed",
                    impact=[*finding.codes, "downstream_use_blocked", fingerprint_marker],
                    evidence_ids=[report.id],
                    opened_by=self.REPORT_SOURCE,
                )
            incident_ids[finding.evidence_id] = incident["id"]
            finding_evidence_ids[finding.evidence_id] = report.id

        aggregate = {
            "schema_version": "evidence-integrity-scan-v1",
            "scanned_at": scanned_at.isoformat(),
            "total": result.total,
            "offset": result.offset,
            "scanned": result.scanned,
            "valid": result.valid,
            "invalid": result.invalid,
            "next_offset": result.next_offset,
            "findings": [
                {"evidence_id": item.evidence_id, "codes": list(item.codes)}
                for item in result.findings
            ],
        }
        aggregate_bytes = self._json_bytes(aggregate)
        scan_report = self.evidence.capture(
            content=aggregate_bytes,
            filename="evidence-integrity-scan.json",
            content_type="application/json",
            source=self.REPORT_SOURCE,
            source_ref=f"scan:{hashlib.sha256(aggregate_bytes).hexdigest()}",
            grade=EvidenceGrade.B,
            effective_at=scanned_at.isoformat(),
            effective_until=None,
            created_by=actor_id,
            metadata={
                "schema_version": "evidence-integrity-scan-v1",
                "retention_class": "security",
                "integrity_scan": True,
            },
        )
        return {
            **asdict(result),
            "findings": [asdict(item) for item in result.findings],
            "scan_evidence_id": scan_report.id,
            "finding_evidence_ids": finding_evidence_ids,
            "incident_ids": incident_ids,
            "automatic_repair": False,
            "automatic_delete": False,
            "automatic_kill_switch_release": False,
        }

    def _finding_report(
        self,
        finding: EvidenceIntegrityFinding,
        *,
        fingerprint: str,
        scanned_at: datetime,
        actor_id: str,
    ):
        source_ref = f"finding:{fingerprint}"
        existing = self.evidence.find_by_source_ref(source=self.REPORT_SOURCE, source_ref=source_ref)
        if existing is not None:
            return existing
        payload = {
            "schema_version": "evidence-integrity-finding-v1",
            "first_observed_at": scanned_at.isoformat(),
            "finding": asdict(finding),
            "fingerprint": fingerprint,
            "original_content_included": False,
        }
        return self.evidence.capture(
            content=self._json_bytes(payload),
            filename=f"{finding.evidence_id}-integrity-finding.json",
            content_type="application/json",
            source=self.REPORT_SOURCE,
            source_ref=source_ref,
            grade=EvidenceGrade.B,
            effective_at=scanned_at.isoformat(),
            effective_until=None,
            created_by=actor_id,
            metadata={
                "schema_version": "evidence-integrity-finding-v1",
                "retention_class": "security",
                "integrity_finding": True,
                "subject_evidence_id": finding.evidence_id,
                "fingerprint": fingerprint,
            },
        )

    @classmethod
    def _fingerprint(cls, finding: EvidenceIntegrityFinding) -> str:
        return hashlib.sha256(cls._json_bytes(asdict(finding))).hexdigest()

    @staticmethod
    def _json_bytes(value: Any) -> bytes:
        return json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()

    @staticmethod
    def _datetime(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Evidence integrity scan as_of must be ISO-8601") from exc
        if parsed.tzinfo is None:
            raise ValueError("Evidence integrity scan as_of must include a timezone")
        return parsed.astimezone(UTC)

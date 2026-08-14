from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from .evidence import EvidenceGrade
from .security import Principal

DIRECT_CONTRACT = "kjds-evidence-scope-v1"
BINDING_CONTRACT = "kjds-evidence-scope-binding-v1"


class ScopedEvidenceAuthority:
    """Project immutable Evidence into one verified operating scope."""

    CONTRACT_ID = "kjds-scoped-evidence-authority-v1"

    def __init__(self, *, evidence) -> None:
        self.evidence = evidence

    def project(
        self,
        *,
        evidence_ids: list[str],
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        if as_of.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        if not principal.can_access_store(store_ref):
            raise PermissionError(
                "Authenticated identity is not authorized for store_ref"
            )
        normalized = sorted(
            {item.strip() for item in evidence_ids if item.strip()}
        )
        supplied = [item for item in evidence_ids if item.strip()]
        if len(normalized) != len(supplied):
            raise ValueError("Duplicate evidence references are not allowed")
        if not normalized:
            return self._empty()

        records: dict[str, Any] = {}
        invalid: list[str] = []
        for evidence_id in normalized:
            try:
                self.evidence.require_current(
                    [evidence_id],
                    as_of=as_of.astimezone(UTC),
                )
                records[evidence_id] = self.evidence.get(evidence_id)
            except (KeyError, RuntimeError, ValueError):
                invalid.append(evidence_id)
        if invalid:
            return self._invalid(
                evidence_ids=normalized,
                records=records,
                invalid=invalid,
            )

        if (
            entity_scope.get("status") != "ready"
            or not entity_scope.get("entity_ref")
        ):
            entity_reason = entity_scope.get(
                "reason",
                "entity_scope_authority_missing",
            )
            projected = [
                self._record(
                    record,
                    status="no_data",
                    authority=None,
                    binding_evidence_id=None,
                    reasons=[entity_reason],
                )
                for record in self._ordered(records)
            ]
            return self._result(
                status="no_data",
                evidence_ids=normalized,
                records=projected,
                source_gaps=[f"evidence_{entity_reason}"],
                blockers=[],
            )

        expected = {
            "tenant_ref": principal.tenant_ref,
            "entity_ref": str(entity_scope["entity_ref"]),
            "store_ref": store_ref,
        }
        bindings: dict[str, list[tuple[Any, list[str]]]] = {}
        binding_records: dict[str, tuple[str, list[str]]] = {}
        conflicts: list[tuple[str, list[str]]] = []

        for record in self._ordered(records):
            metadata = self._metadata(record)
            if metadata.get("evidence_scope_contract_id") != BINDING_CONTRACT:
                continue
            reasons = self._binding_reasons(
                binding=record,
                records=records,
                expected=expected,
            )
            target_id = str(metadata.get("target_evidence_id", "")).strip()
            binding_records[record.id] = (target_id, reasons)
            if reasons:
                conflicts.append((record.id, reasons))
                continue
            bindings.setdefault(target_id, []).append((record, reasons))

        projected: list[dict[str, Any]] = []
        unbound: list[str] = []
        for record in self._ordered(records):
            metadata = self._metadata(record)
            contract = metadata.get("evidence_scope_contract_id")
            if contract == BINDING_CONTRACT:
                _, reasons = binding_records[record.id]
                projected.append(
                    self._record(
                        record,
                        status="blocked" if reasons else "ready",
                        authority=(
                            None if reasons else BINDING_CONTRACT
                        ),
                        binding_evidence_id=(
                            None if reasons else record.id
                        ),
                        reasons=reasons,
                    )
                )
                continue
            if contract == DIRECT_CONTRACT:
                reasons = self._direct_reasons(
                    record=record,
                    expected=expected,
                )
                if reasons:
                    conflicts.append((record.id, reasons))
                projected.append(
                    self._record(
                        record,
                        status="blocked" if reasons else "ready",
                        authority=None if reasons else DIRECT_CONTRACT,
                        binding_evidence_id=None,
                        reasons=reasons,
                    )
                )
                continue
            valid_bindings = bindings.get(record.id, [])
            if valid_bindings:
                binding = sorted(
                    (item[0] for item in valid_bindings),
                    key=lambda item: item.id,
                )[0]
                projected.append(
                    self._record(
                        record,
                        status="ready",
                        authority=BINDING_CONTRACT,
                        binding_evidence_id=binding.id,
                        reasons=[],
                    )
                )
            else:
                unbound.append(record.id)
                projected.append(
                    self._record(
                        record,
                        status="unbound",
                        authority=None,
                        binding_evidence_id=None,
                        reasons=["evidence_scope_binding_missing"],
                    )
                )

        if conflicts:
            blockers = [
                self._blocker(
                    f"evidence_scope_conflict:{evidence_id}",
                    severity="P0",
                    next_action=(
                        "Replace the conflicting scope binding with an "
                        "independent grade A binding for the exact target hash."
                    ),
                    workspace=f"/evidence/{evidence_id}",
                )
                for evidence_id, _ in sorted(conflicts)
            ]
            return self._result(
                status="blocked",
                evidence_ids=normalized,
                records=projected,
                source_gaps=sorted(
                    {
                        f"evidence_scope_conflict:{reason}"
                        for _, reasons in conflicts
                        for reason in reasons
                    }
                ),
                blockers=blockers,
            )
        if unbound:
            return self._result(
                status="partial",
                evidence_ids=normalized,
                records=projected,
                source_gaps=["evidence_scope_binding_missing"],
                blockers=[
                    self._blocker(
                        "evidence_scope_binding_missing",
                        severity="P0",
                        next_action=(
                            "Create an immutable independent scope binding "
                            "for every business Evidence target."
                        ),
                        workspace="/evidence",
                    )
                ],
            )
        return self._result(
            status="ready",
            evidence_ids=normalized,
            records=projected,
            source_gaps=[],
            blockers=[],
        )

    def project_targets(
        self,
        *,
        evidence_ids: list[str],
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        """Project targets plus their current independent binding Evidence."""
        normalized = sorted(
            {item.strip() for item in evidence_ids if item.strip()}
        )
        binding_ids = self.evidence.find_binding_ids(
            target_evidence_ids=normalized,
            binding_contract_id=BINDING_CONTRACT,
            as_of=as_of,
        )
        return self.project(
            evidence_ids=[*normalized, *binding_ids],
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )

    def _binding_reasons(
        self,
        *,
        binding,
        records: dict[str, Any],
        expected: dict[str, str],
    ) -> list[str]:
        metadata = self._metadata(binding)
        reasons = self._scope_reasons(metadata, expected)
        target_id = str(metadata.get("target_evidence_id", "")).strip()
        target = records.get(target_id)
        if target is None:
            reasons.append("binding_target_not_in_snapshot")
            return sorted(set(reasons))
        target_hash = str(
            metadata.get("target_evidence_sha256", "")
        ).strip()
        if target_hash != target.sha256:
            reasons.append("binding_target_hash_mismatch")
        if self._grade(binding) != EvidenceGrade.A.value:
            reasons.append("binding_requires_grade_a")
        reviewed_by = str(metadata.get("reviewed_by", "")).strip()
        binding_creator = str(getattr(binding, "created_by", "")).strip()
        target_creator = str(getattr(target, "created_by", "")).strip()
        if (
            not reviewed_by
            or not binding_creator
            or reviewed_by in (binding_creator, target_creator)
            or binding_creator == target_creator
        ):
            reasons.append("binding_independence_missing")
        return sorted(set(reasons))

    def _direct_reasons(
        self,
        *,
        record,
        expected: dict[str, str],
    ) -> list[str]:
        metadata = self._metadata(record)
        reasons = self._scope_reasons(metadata, expected)
        reviewed_by = str(metadata.get("reviewed_by", "")).strip()
        creator = str(getattr(record, "created_by", "")).strip()
        if not reviewed_by or not creator or reviewed_by == creator:
            reasons.append("direct_scope_independence_missing")
        return sorted(set(reasons))

    @staticmethod
    def _scope_reasons(
        metadata: dict[str, Any],
        expected: dict[str, str],
    ) -> list[str]:
        return [
            f"{field}_mismatch"
            for field, value in expected.items()
            if metadata.get(field) != value
        ]

    @classmethod
    def _record(
        cls,
        record,
        *,
        status: str,
        authority: str | None,
        binding_evidence_id: str | None,
        reasons: list[str],
    ) -> dict[str, Any]:
        return {
            "evidence_id": record.id,
            "sha256": record.sha256,
            "grade": cls._grade(record),
            "source": record.source,
            "source_ref": record.source_ref,
            "effective_at": record.effective_at,
            "effective_until": record.effective_until,
            "scope_binding": {
                "status": status,
                "authority": authority,
                "binding_evidence_id": binding_evidence_id,
                "reasons": reasons,
            },
        }

    @classmethod
    def _invalid(
        cls,
        *,
        evidence_ids: list[str],
        records: dict[str, Any],
        invalid: list[str],
    ) -> dict[str, Any]:
        projected = [
            cls._record(
                record,
                status="blocked",
                authority=None,
                binding_evidence_id=None,
                reasons=["evidence_integrity_invalid"],
            )
            for record in cls._ordered(records)
        ]
        return cls._result(
            status="blocked",
            evidence_ids=evidence_ids,
            records=projected,
            source_gaps=["invalid_evidence"],
            blockers=[
                cls._blocker(
                    f"invalid_evidence:{evidence_id}",
                    severity="P0",
                    next_action=(
                        "Restore or replace the invalid immutable Evidence "
                        "record."
                    ),
                    workspace=f"/evidence/{evidence_id}",
                )
                for evidence_id in invalid
            ],
            invalid_evidence_ids=invalid,
        )

    @classmethod
    def _empty(cls) -> dict[str, Any]:
        return cls._result(
            status="no_data",
            evidence_ids=[],
            records=[],
            source_gaps=["evidence_scope_not_bound"],
            blockers=[
                cls._blocker(
                    "evidence_scope_not_bound",
                    severity="P1",
                    next_action=(
                        "Bind immutable source Evidence to this decision scope."
                    ),
                    workspace="/evidence",
                )
            ],
        )

    @classmethod
    def _result(
        cls,
        *,
        status: str,
        evidence_ids: list[str],
        records: list[dict[str, Any]],
        source_gaps: list[str],
        blockers: list[dict[str, Any]],
        invalid_evidence_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        binding_projection = [
            {
                "evidence_id": item["evidence_id"],
                "sha256": item["sha256"],
                "scope_binding": item["scope_binding"],
            }
            for item in records
        ]
        return {
            "contract_id": cls.CONTRACT_ID,
            "status": status,
            "evidence_ids": evidence_ids,
            "records": records,
            "invalid_evidence_ids": invalid_evidence_ids or [],
            "snapshot_sha256": (
                cls._hash(records) if records else None
            ),
            "binding_authority_sha256": (
                cls._hash(binding_projection)
                if binding_projection
                else None
            ),
            "source_gaps": source_gaps,
            "blockers": blockers,
        }

    @staticmethod
    def _blocker(
        code: str,
        *,
        severity: str,
        next_action: str,
        workspace: str,
    ) -> dict[str, Any]:
        return {
            "code": code,
            "severity": severity,
            "owner": "evidence-governance",
            "sla": "before candidate scoring or Pilot approval",
            "next": next_action,
            "next_workspace": workspace,
        }

    @staticmethod
    def _metadata(record) -> dict[str, Any]:
        value = getattr(record, "metadata", {})
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _grade(record) -> str:
        value = getattr(record, "grade", EvidenceGrade.UNKNOWN)
        return value.value if isinstance(value, EvidenceGrade) else str(value)

    @staticmethod
    def _ordered(records: dict[str, Any]) -> list[Any]:
        return [records[item] for item in sorted(records)]

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

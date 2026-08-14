from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from .security import Principal

FORMAL_DELIVERY_READBACK_CONTRACT_ID = (
    "kjds-formal-exact-scope-delivery-readback-v1"
)
AUTHORIZED_ADAPTER_CONTRACT_ID = (
    "kjds-authorized-delivery-readback-adapter-v1"
)


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), default=str
        ).encode()
    ).hexdigest()


def _timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


class DisabledDeliveryReadbackSource:
    """No-data production default when no authorized read source is bound."""

    def project(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        scope = {
            "tenant_ref": principal.tenant_ref,
            "entity_ref": str(entity_scope.get("entity_ref") or "") or None,
            "store_ref": store_ref,
        }
        payload = {
            "contract_id": FORMAL_DELIVERY_READBACK_CONTRACT_ID,
            "status": "no_data",
            "as_of": as_of.isoformat(),
            "scope": scope,
            "readbacks": [],
            "source_gaps": ["formal_delivery_readback_source_unbound"],
            "authority": {
                "source_kind": None,
                "adapter_id": None,
                "adapter_version": None,
                "authorization_evidence_id": None,
                "immutable": True,
                "revoked": False,
            },
            "control_envelope": {
                "raw_reads": [],
                "official_adapter_bound": False,
                "formal_export_bound": False,
                "private_erp_interface_allowed": False,
                "external_write_allowed": False,
            },
        }
        payload["snapshot_sha256"] = _hash(payload)
        return payload


class AuthorizedDeliveryReadbackSource:
    """Validate an official API or written-authorized export read-only port."""

    SOURCE_KINDS = frozenset(
        {"official_public_api", "authorized_formal_export"}
    )
    EVIDENCE_SOURCES = frozenset(
        {
            "delivery_readback_adapter_authorization",
            "official_delivery_readback",
            "authorized_delivery_readback_export",
            "carrier_final_bill",
        }
    )

    def __init__(
        self,
        *,
        reader: Callable[..., dict[str, Any]],
        evidence,
        scoped_evidence,
        adapter_id: str,
        adapter_version: str,
        source_kind: str,
        authorization_evidence_id: str,
        authorization_evidence_sha256: str,
    ) -> None:
        self.reader = reader
        self.evidence = evidence
        self.scoped_evidence = scoped_evidence
        self.adapter_id = adapter_id
        self.adapter_version = adapter_version
        self.source_kind = source_kind
        self.authorization_evidence_id = authorization_evidence_id
        self.authorization_evidence_sha256 = (
            authorization_evidence_sha256
        )

    def project(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        scope = self._scope(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
        )
        if scope["entity_ref"] is None:
            return DisabledDeliveryReadbackSource().project(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                as_of=as_of,
            )
        authority_issues = self._authorization_issues(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        if authority_issues:
            return self._blocked(
                scope=scope,
                as_of=as_of,
                gaps=authority_issues,
                raw_reads=[],
            )
        try:
            envelope = self.reader(
                tenant_ref=scope["tenant_ref"],
                entity_ref=scope["entity_ref"],
                store_ref=scope["store_ref"],
                as_of=as_of.isoformat(),
            )
        except TimeoutError:
            return self._blocked(
                scope=scope,
                as_of=as_of,
                gaps=["formal_delivery_readback_timeout"],
                raw_reads=["authorized_delivery_readback"],
            )
        except (KeyError, RuntimeError, TypeError, ValueError):
            return self._blocked(
                scope=scope,
                as_of=as_of,
                gaps=["formal_delivery_readback_source_error"],
                raw_reads=["authorized_delivery_readback"],
            )
        issues = self._envelope_issues(
            envelope=envelope,
            scope=scope,
            as_of=as_of,
        )
        if issues:
            return self._blocked(
                scope=scope,
                as_of=as_of,
                gaps=issues,
                raw_reads=["authorized_delivery_readback"],
            )
        if envelope["outcome"] == "no_data":
            return self._result(
                scope=scope,
                as_of=as_of,
                status="no_data",
                readbacks=[],
                gaps=["formal_delivery_readback_missing"],
                raw_reads=["authorized_delivery_readback"],
            )
        readbacks, replay_issues = self._deduplicate(
            list(envelope.get("readbacks", []))
        )
        if replay_issues:
            return self._blocked(
                scope=scope,
                as_of=as_of,
                gaps=replay_issues,
                raw_reads=["authorized_delivery_readback"],
            )
        evidence_issues = [
            issue
            for readback in readbacks
            for issue in self._readback_evidence_issues(
                readback=readback,
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                as_of=as_of,
            )
        ]
        if evidence_issues:
            return self._blocked(
                scope=scope,
                as_of=as_of,
                gaps=sorted(set(evidence_issues)),
                raw_reads=["authorized_delivery_readback"],
            )
        return self._result(
            scope=scope,
            as_of=as_of,
            status="ready" if readbacks else "no_data",
            readbacks=readbacks,
            gaps=[] if readbacks else ["formal_delivery_readback_missing"],
            raw_reads=["authorized_delivery_readback"],
        )

    def _authorization_issues(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> list[str]:
        if (
            self.source_kind not in self.SOURCE_KINDS
            or not self.adapter_id.strip()
            or not self.adapter_version.strip()
            or len(self.authorization_evidence_sha256) != 64
        ):
            return ["formal_delivery_adapter_identity_invalid"]
        try:
            self.evidence.require_current(
                [self.authorization_evidence_id], as_of=as_of
            )
            record = self.evidence.get(self.authorization_evidence_id)
            projection = self.scoped_evidence.project_targets(
                evidence_ids=[self.authorization_evidence_id],
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                as_of=as_of,
            )
        except (KeyError, RuntimeError, ValueError):
            return ["formal_delivery_adapter_authorization_invalid"]
        metadata = getattr(record, "metadata", None) or {}
        target = next(
            (
                item
                for item in projection.get("records", [])
                if item.get("evidence_id", item.get("id"))
                == self.authorization_evidence_id
            ),
            None,
        )
        if (
            str(getattr(record, "source", ""))
            != "delivery_readback_adapter_authorization"
            or str(getattr(record, "sha256", ""))
            != self.authorization_evidence_sha256
            or projection.get("status") != "ready"
            or target is None
            or (
                target.get("status")
                or (target.get("scope_binding") or {}).get("status")
            )
            != "ready"
            or metadata.get("adapter_id") != self.adapter_id
            or metadata.get("adapter_version") != self.adapter_version
            or metadata.get("source_kind") != self.source_kind
            or metadata.get("authorization_status") != "active"
            or metadata.get("revoked") is not False
        ):
            return ["formal_delivery_adapter_authorization_invalid"]
        return []

    def _envelope_issues(
        self,
        *,
        envelope: dict[str, Any],
        scope: dict[str, Any],
        as_of: datetime,
    ) -> list[str]:
        issues: list[str] = []
        if (
            envelope.get("contract_id")
            != AUTHORIZED_ADAPTER_CONTRACT_ID
            or envelope.get("schema_version") != "1.0"
        ):
            issues.append("formal_delivery_readback_schema_drift")
        if envelope.get("scope") != scope:
            issues.append("formal_delivery_readback_scope_drift")
        if (
            envelope.get("adapter_id") != self.adapter_id
            or envelope.get("adapter_version") != self.adapter_version
            or envelope.get("source_kind") != self.source_kind
        ):
            issues.append("formal_delivery_readback_adapter_drift")
        observed_at = _timestamp(envelope.get("observed_at"))
        if observed_at is None or observed_at > as_of:
            issues.append("formal_delivery_readback_as_of_invalid")
        if envelope.get("revoked") is not False:
            issues.append("formal_delivery_readback_revoked")
        if envelope.get("outcome") not in {"succeeded", "no_data"}:
            issues.append("formal_delivery_readback_outcome_unknown")
        expected_hash = _hash(
            {
                key: value
                for key, value in envelope.items()
                if key != "payload_sha256"
            }
        )
        if envelope.get("payload_sha256") != expected_hash:
            issues.append("formal_delivery_readback_payload_hash_drift")
        return issues

    def _deduplicate(
        self, readbacks: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        by_id: dict[str, dict[str, Any]] = {}
        for readback in readbacks:
            readback_id = str(readback.get("readback_id") or "")
            if not readback_id:
                return [], ["formal_delivery_readback_identity_missing"]
            existing = by_id.get(readback_id)
            if existing is not None and _hash(existing) != _hash(readback):
                return [], ["formal_delivery_readback_replay_conflict"]
            by_id[readback_id] = readback
        return [by_id[key] for key in sorted(by_id)], []

    def _readback_evidence_issues(
        self,
        *,
        readback: dict[str, Any],
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> list[str]:
        evidence_id = str(readback.get("readback_evidence_id") or "")
        expected_sha = str(
            readback.get("readback_evidence_sha256") or ""
        )
        try:
            self.evidence.require_current([evidence_id], as_of=as_of)
            record = self.evidence.get(evidence_id)
            projection = self.scoped_evidence.project_targets(
                evidence_ids=[evidence_id],
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                as_of=as_of,
            )
        except (KeyError, RuntimeError, ValueError):
            return ["formal_delivery_readback_evidence_invalid"]
        metadata = getattr(record, "metadata", None) or {}
        target = next(
            (
                item
                for item in projection.get("records", [])
                if item.get("evidence_id", item.get("id"))
                == evidence_id
            ),
            None,
        )
        if (
            str(getattr(record, "source", ""))
            not in self.EVIDENCE_SOURCES
            or str(getattr(record, "sha256", "")) != expected_sha
            or projection.get("status") != "ready"
            or target is None
            or (
                target.get("status")
                or (target.get("scope_binding") or {}).get("status")
            )
            != "ready"
            or metadata.get("adapter_id") != self.adapter_id
            or metadata.get("readback_id") != readback.get("readback_id")
            or metadata.get("order_external_id")
            != readback.get("order_external_id")
            or metadata.get("shipment_id") != readback.get("shipment_id")
            or metadata.get("outcome") != "succeeded"
            or metadata.get("revoked") is not False
        ):
            return ["formal_delivery_readback_evidence_binding_drift"]
        for leg in readback.get("legs", []):
            leg["evidence_status"] = "current"
            leg["evidence_revoked"] = False
        return []

    def _result(
        self,
        *,
        scope: dict[str, Any],
        as_of: datetime,
        status: str,
        readbacks: list[dict[str, Any]],
        gaps: list[str],
        raw_reads: list[str],
    ) -> dict[str, Any]:
        payload = {
            "contract_id": FORMAL_DELIVERY_READBACK_CONTRACT_ID,
            "status": status,
            "as_of": as_of.isoformat(),
            "scope": scope,
            "readbacks": readbacks,
            "source_gaps": gaps,
            "authority": {
                "source_kind": self.source_kind,
                "adapter_id": self.adapter_id,
                "adapter_version": self.adapter_version,
                "authorization_evidence_id": (
                    self.authorization_evidence_id
                ),
                "immutable": True,
                "revoked": False,
            },
            "control_envelope": {
                "raw_reads": raw_reads,
                "official_adapter_bound": (
                    self.source_kind == "official_public_api"
                ),
                "formal_export_bound": (
                    self.source_kind == "authorized_formal_export"
                ),
                "private_erp_interface_allowed": False,
                "external_write_allowed": False,
            },
        }
        payload["snapshot_sha256"] = _hash(payload)
        return payload

    def _blocked(
        self,
        *,
        scope: dict[str, Any],
        as_of: datetime,
        gaps: list[str],
        raw_reads: list[str],
    ) -> dict[str, Any]:
        return self._result(
            scope=scope,
            as_of=as_of,
            status="blocked",
            readbacks=[],
            gaps=sorted(set(gaps)),
            raw_reads=raw_reads,
        )

    @staticmethod
    def _scope(
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
    ) -> dict[str, Any]:
        if not principal.can_access_store(store_ref):
            raise PermissionError("delivery readback store scope is invalid")
        tenant_ref = str(
            entity_scope.get("tenant_ref") or principal.tenant_ref
        ).strip()
        granted_store = str(
            entity_scope.get("store_ref") or store_ref
        ).strip()
        if tenant_ref != principal.tenant_ref or granted_store != store_ref:
            raise PermissionError("delivery readback scope is invalid")
        return {
            "tenant_ref": tenant_ref,
            "entity_ref": (
                str(entity_scope.get("entity_ref") or "").strip() or None
            ),
            "store_ref": store_ref,
        }

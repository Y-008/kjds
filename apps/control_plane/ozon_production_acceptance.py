"""Read-only production acceptance for official Ozon observations.

This module is deliberately an admission *projection*.  It does not acquire
credentials, contact Ozon, promote facts, issue a Permit, or perform an
external write.  A completed read-only Pilot run becomes admissible only when
the exact scoped run, immutable raw response, official response contract,
freshness window, and server-owned channel runtime identity all agree.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from .ozon_live_contracts import FINANCE_TRANSACTION_PATH
from .provider_readback_verifier import (
    READBACK_FINANCE_CONTRACT_VERSION,
    READBACK_PRODUCT_ATTRIBUTE_PATHS,
    READBACK_PRODUCT_CONTRACT_VERSION,
    READBACK_PRODUCT_INFO_PATH,
    ProviderReadbackVerifier,
)
from .security import Principal


class OzonProductionAcceptanceError(ValueError):
    """A stable, non-sensitive acceptance contract failure."""


class OzonProductionAcceptanceService:
    """Evaluate one scoped Ozon read run without mutating business state.

    ``scoped_pilots`` is the SQL-first authority for tenant/entity/store
    isolation.  ``channel_account_reader`` is a server-owned projection of the
    managed credential lease and independent provider readback; callers cannot
    provide either authority in the request.
    """

    CONTRACT_ID = "kjds-ozon-production-acceptance-v1"
    CONTRACT_VERSION = "1.0.0"
    DEFAULT_FRESHNESS_SECONDS = 900
    OPERATIONS = {
        "ozon.product.read": {
            "contract_version": READBACK_PRODUCT_CONTRACT_VERSION,
            "required_capability": "catalog.read",
        },
        "ozon.finance.read": {
            "contract_version": READBACK_FINANCE_CONTRACT_VERSION,
            "required_capability": "finance.read",
        },
    }

    def __init__(
        self,
        *,
        scoped_pilots: Any,
        evidence: Any,
        channel_account_reader: Any = None,
        clock: Any = None,
        freshness_seconds: int = DEFAULT_FRESHNESS_SECONDS,
        readback_verifier: Any = None,
    ) -> None:
        if not isinstance(freshness_seconds, int) or isinstance(
            freshness_seconds, bool
        ) or not 60 <= freshness_seconds <= 86_400:
            raise ValueError("Ozon acceptance freshness must be between 60 and 86400 seconds")
        self.scoped_pilots = scoped_pilots
        self.evidence = evidence
        self.channel_account_reader = channel_account_reader
        self.clock = clock or (lambda: datetime.now(UTC))
        self.freshness_seconds = freshness_seconds
        self.readback_verifier = readback_verifier or ProviderReadbackVerifier()

    def evaluate(
        self,
        *,
        principal: Principal,
        entity_scope: Mapping[str, Any],
        store_ref: str,
        run_id: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        cutoff = self._aware(as_of, "as_of")
        now = self._aware(self.clock(), "clock")
        if cutoff > now:
            raise OzonProductionAcceptanceError("as_of cannot be in the future")
        if not isinstance(entity_scope, Mapping):
            raise OzonProductionAcceptanceError("entity_scope must be an object")
        if not principal.can_access_store(str(store_ref)):
            raise PermissionError("Authenticated identity is not authorized for store_ref")
        run_ref = self._required(run_id, "run_id", 300)
        scope = self._scope(principal, entity_scope, store_ref)

        # A missing entity authority is a normal no-data state for a newly
        # provisioned tenant.  Return a safe projection without touching the
        # Pilot/Run/Evidence stores, preserving the SQL-first isolation rule.
        if scope["entity_ref"] is None:
            return self._result(
                status="no_data",
                gate_status="NO_DATA",
                scope=scope,
                run=None,
                checks={"exact_scope": False},
                blockers=["entity_scope_authority_missing"],
                evidence_ids=[],
                source_contract=None,
                runtime_identity=None,
                next_action="Obtain a current exact tenant/entity/store scope grant before running Ozon acceptance.",
            )

        # ``require_run`` performs the canonical SQL scope join and rechecks
        # the Pilot's current independent Evidence.  Preserve not-found and
        # permission semantics so a cross-tenant ID cannot be used as a probe.
        try:
            run = self.scoped_pilots.require_run(
                run_ref,
                principal=principal,
                entity_scope=dict(entity_scope),
                store_ref=str(store_ref),
                as_of=cutoff,
            )
        except (KeyError, PermissionError):
            raise
        except (RuntimeError, TypeError, ValueError):
            return self._result(
                status="blocked",
                gate_status="BLOCKED_EVIDENCE",
                scope=scope,
                run=None,
                checks={"exact_scope": False},
                blockers=["scoped_read_run_not_admissible"],
                evidence_ids=[],
                source_contract=None,
                runtime_identity=None,
                next_action="Re-establish the current scoped Pilot and its independently bound Evidence.",
            )

        checks: dict[str, bool] = {}
        blockers: list[str] = []

        def check(name: str, passed: bool, blocker: str) -> None:
            value = passed is True
            checks[name] = value
            if not value:
                blockers.append(blocker)

        run_scope = run.get("scope") if isinstance(run, Mapping) else None
        check(
            "exact_scope",
            isinstance(run_scope, Mapping)
            and all(
                run_scope.get(field) == scope.get(field)
                for field in ("tenant_ref", "entity_ref", "store_ref")
            ),
            "RUN_SCOPE_DRIFT",
        )
        operation = str(run.get("operation") or "") if isinstance(run, Mapping) else ""
        contract = self.OPERATIONS.get(operation)
        check("supported_operation", contract is not None, "OZON_OPERATION_NOT_ADMITTED")
        check(
            "completed_success",
            isinstance(run, Mapping)
            and run.get("status") == "completed"
            and run.get("outcome") == "succeeded"
            and not run.get("error_code"),
            "RUN_NOT_SUCCESSFUL",
        )
        check(
            "immutable_completion",
            isinstance(run, Mapping)
            and run.get("immutable_after_completion") is True,
            "RUN_COMPLETION_NOT_IMMUTABLE",
        )
        raw_id = run.get("raw_response_evidence_id") if isinstance(run, Mapping) else None
        check(
            "raw_response_reference",
            isinstance(raw_id, str) and bool(raw_id.strip()),
            "RAW_RESPONSE_REFERENCE_MISSING",
        )
        check(
            "raw_response_run_flags",
            isinstance(run, Mapping)
            and run.get("raw_response_stored") is True
            and run.get("raw_response_verified") is True
            and run.get("raw_response_integrity_code") is None,
            "RAW_RESPONSE_RUN_NOT_VERIFIED",
        )
        # A transport/schema failure can leave a completed bookkeeping row
        # without an immutable raw artifact.  Keep this distinct from
        # ``NO_DATA`` so callers cannot mistake an attempted read for an
        # admissible observation.
        run_error_code = (
            str(run.get("error_code") or "").strip().upper()
            if isinstance(run, Mapping)
            else ""
        )
        check(
            "readback_artifact_present",
            isinstance(raw_id, str)
            and bool(raw_id.strip())
            and isinstance(run, Mapping)
            and run.get("raw_response_stored") is True
            and isinstance(run.get("response_sha256"), str)
            and isinstance(run.get("response_byte_size"), int)
            and run.get("response_byte_size") > 0,
            "OZON_READBACK_ARTIFACT_MISSING",
        )
        if run_error_code:
            blockers.append(
                "OZON_READ_TRANSPORT_FAILED"
                if "TRANSPORT" in run_error_code
                else "OZON_READ_ATTEMPT_FAILED"
            )

        record = None
        verification = None
        bundle_bytes: bytes | None = None
        raw_ids: list[str] = []
        if isinstance(raw_id, str) and raw_id.strip():
            try:
                raw_ids = list(
                    self.evidence.target_evidence_ids(
                        target_type="read_only_pilot_run",
                        target_id=run_ref,
                        relationship="raw_response",
                    )
                )
            except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
                raw_ids = []
            check(
                "raw_response_unique_lineage",
                raw_ids == [raw_id],
                "RAW_RESPONSE_LINEAGE_INVALID",
            )
            try:
                record, verification = self.evidence.inspect_integrity(raw_id)
                bundle_bytes, _ = self.evidence.content(raw_id)
            except (KeyError, RuntimeError, TypeError, ValueError):
                record = None
                verification = None
                bundle_bytes = None
            check(
                "raw_response_integrity",
                verification is not None
                and self._value(verification, "valid") is True
                and self._value(verification, "actual_sha256")
                == (run.get("response_sha256") if isinstance(run, Mapping) else None)
                and self._value(verification, "byte_size")
                == (run.get("response_byte_size") if isinstance(run, Mapping) else None),
                "RAW_RESPONSE_INTEGRITY_INVALID",
            )
            check(
                "raw_response_contract_metadata",
                record is not None
                and self._value(record, "source") == "ozon-isolated-read-worker"
                and self._value(record, "source_ref") == run_ref
                and self._value(record, "content_type") == "application/json"
                and self._grade(record) == "A"
                and self._metadata(record).get("raw_response_stored") is True
                and self._metadata(record).get("response_sha256")
                == (run.get("response_sha256") if isinstance(run, Mapping) else None),
                "RAW_RESPONSE_METADATA_INVALID",
            )

        expected_contract = contract["contract_version"] if contract else ""
        parsed_bundle: dict[str, Any] | None = None
        if bundle_bytes is not None and expected_contract:
            try:
                parser = getattr(self.readback_verifier, "parse_bundle_contract", None)
                if not callable(parser):
                    parser = getattr(self.readback_verifier, "_parse_bundle", None)
                parsed_bundle = parser(bundle_bytes, expected_contract) if callable(parser) else None
            except (TypeError, ValueError, KeyError, json.JSONDecodeError):
                parsed_bundle = None
        check(
            "official_response_contract",
            parsed_bundle is not None,
            "OZON_RESPONSE_CONTRACT_INVALID",
        )
        check(
            "target_binding",
            self._target_binding(
                operation=operation,
                run=run,
                parsed_bundle=parsed_bundle,
            ),
            "OZON_TARGET_BINDING_INVALID",
        )
        check(
            "evidence_current",
            self._evidence_current(record, cutoff),
            "RAW_RESPONSE_EVIDENCE_STALE",
        )
        check(
            "observation_fresh",
            self._observation_fresh(record, cutoff),
            "OZON_OBSERVATION_STALE",
        )
        source_contract = self._source_contract(operation, expected_contract)
        check(
            "official_adapter_contract",
            source_contract is not None,
            "OZON_SOURCE_CONTRACT_NOT_REGISTERED",
        )

        runtime_identity, runtime_blockers = self._runtime_identity(
            principal=principal,
            entity_scope=dict(entity_scope),
            store_ref=str(store_ref),
            as_of=cutoff,
            required_capability=(contract["required_capability"] if contract else None),
        )
        check("runtime_identity", not runtime_blockers, "CHANNEL_RUNTIME_IDENTITY_NOT_FRESH")
        blockers.extend(runtime_blockers)

        accepted = not blockers and all(checks.values())
        return self._result(
            status="accepted" if accepted else "blocked",
            gate_status="PASS" if accepted else "BLOCKED_EVIDENCE",
            scope=scope,
            run=self._safe_run(run),
            checks=checks,
            blockers=sorted(set(blockers)),
            evidence_ids=[raw_id] if isinstance(raw_id, str) and raw_id.strip() else [],
            source_contract=source_contract,
            runtime_identity=runtime_identity,
            next_action=(
                "External Ozon read Evidence is admissible for downstream scoped replay; fact promotion remains a separate gate."
                if accepted
                else "Resolve every acceptance blocker, capture a fresh official read, and rerun this projection."
            ),
        )

    def _runtime_identity(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        required_capability: str | None,
    ) -> tuple[dict[str, Any] | None, list[str]]:
        reader = self.channel_account_reader
        if reader is None:
            return None, ["channel_account_runtime_identity_reader_unbound"]
        try:
            if callable(reader) and not hasattr(reader, "project"):
                payload = reader(
                    principal=principal,
                    entity_scope=entity_scope,
                    store_ref=store_ref,
                    as_of=as_of,
                )
            else:
                payload = reader.project(
                    principal=principal,
                    entity_scope=entity_scope,
                    store_ref=store_ref,
                    as_of=as_of,
                    platform="ozon",
                    page_size=100,
                )
        except (KeyError, PermissionError, RuntimeError, TypeError, ValueError):
            return None, ["channel_account_runtime_identity_reader_failed"]
        if not isinstance(payload, Mapping):
            return None, ["channel_account_runtime_identity_payload_invalid"]
        items = payload.get("items")
        if not isinstance(items, list):
            return None, ["channel_account_runtime_identity_items_invalid"]
        candidates = [
            item
            for item in items
            if isinstance(item, Mapping) and item.get("platform") == "ozon"
        ]
        if len(candidates) != 1:
            return None, [
                "channel_account_runtime_identity_missing"
                if not candidates
                else "channel_account_runtime_identity_ambiguous"
            ]
        item = candidates[0]
        adapter = item.get("adapter")
        runtime = item.get("runtime_identity")
        capabilities = item.get("capabilities")
        required_flags = (
            "managed_store_bound",
            "lease_fresh",
            "fingerprint_match",
            "scope_match",
            "capabilities_match",
            "provider_readback_fresh_passed",
            "external_verifier_fresh_passed",
        )
        blockers: list[str] = []
        if item.get("state") != "ready":
            blockers.append("channel_account_state_not_ready")
        if not isinstance(adapter, Mapping) or adapter.get("read_only") is not True:
            blockers.append("channel_account_adapter_not_read_only")
        if not isinstance(runtime, Mapping) or runtime.get("status") != "fresh_passed":
            blockers.append("channel_account_runtime_identity_not_fresh")
        if isinstance(runtime, Mapping):
            blockers.extend(
                f"channel_account_{flag}"
                for flag in required_flags
                if runtime.get(flag) is not True
            )
        if required_capability and (
            not isinstance(capabilities, list) or required_capability not in capabilities
        ):
            blockers.append("channel_account_required_capability_missing")
        # Return only non-secret identity facts.  Credential references and
        # fingerprints remain inside the governed authority and never leave
        # this projection.
        safe = {
            "platform": "ozon",
            "account_ref": item.get("account_ref"),
            "adapter": {
                "adapter_id": adapter.get("adapter_id") if isinstance(adapter, Mapping) else None,
                "adapter_version": adapter.get("adapter_version") if isinstance(adapter, Mapping) else None,
                "read_only": adapter.get("read_only") is True if isinstance(adapter, Mapping) else False,
            },
            "state": item.get("state"),
            "runtime_status": runtime.get("status") if isinstance(runtime, Mapping) else None,
            "required_capability": required_capability,
            "capabilities_match": runtime.get("capabilities_match") is True if isinstance(runtime, Mapping) else False,
            "provider_readback_fresh_passed": runtime.get("provider_readback_fresh_passed") is True if isinstance(runtime, Mapping) else False,
            "external_verifier_fresh_passed": runtime.get("external_verifier_fresh_passed") is True if isinstance(runtime, Mapping) else False,
        }
        return safe, sorted(set(blockers))

    def _source_contract(self, operation: str, expected_contract: str) -> dict[str, Any] | None:
        if operation == "ozon.finance.read" and expected_contract == READBACK_FINANCE_CONTRACT_VERSION:
            return {
                "platform": "ozon",
                "operation": operation,
                "origin": "https://api-seller.ozon.ru",
                "method": "POST",
                "path": FINANCE_TRANSACTION_PATH,
                "contract_version": expected_contract,
            }
        if operation == "ozon.product.read" and expected_contract == READBACK_PRODUCT_CONTRACT_VERSION:
            return {
                "platform": "ozon",
                "operation": operation,
                "origin": "https://api-seller.ozon.ru",
                "method": "POST",
                "paths": [READBACK_PRODUCT_INFO_PATH, *sorted(READBACK_PRODUCT_ATTRIBUTE_PATHS)],
                "contract_version": expected_contract,
            }
        return None

    @staticmethod
    def _target_binding(*, operation: str, run: Mapping[str, Any], parsed_bundle: Mapping[str, Any] | None) -> bool:
        if parsed_bundle is None:
            return False
        if operation == "ozon.product.read":
            return parsed_bundle.get("offer_id_sha256") == run.get("target_hash")
        if operation == "ozon.finance.read":
            summary = run.get("summary")
            return (
                isinstance(summary, Mapping)
                and parsed_bundle.get("operation") == "ozon.finance.read"
                and parsed_bundle.get("query_window_sha256") == summary.get("query_window_sha256")
                and parsed_bundle.get("page") == summary.get("page")
                and parsed_bundle.get("page_size") == summary.get("page_size")
                and parsed_bundle.get("operation_count") == summary.get("operation_count")
                and parsed_bundle.get("page_count") == summary.get("page_count")
            )
        return False

    def _evidence_current(self, record: Any, cutoff: datetime) -> bool:
        if record is None:
            return False
        try:
            effective_at = self._aware(self._value(record, "effective_at"), "effective_at")
            effective_until_raw = self._value(record, "effective_until")
            effective_until = (
                self._aware(effective_until_raw, "effective_until")
                if effective_until_raw
                else None
            )
        except (TypeError, ValueError):
            return False
        return effective_at <= cutoff and (effective_until is None or cutoff < effective_until)

    def _observation_fresh(self, record: Any, cutoff: datetime) -> bool:
        if record is None:
            return False
        metadata = self._metadata(record)
        raw = metadata.get("observed_at") or self._value(record, "recorded_at")
        try:
            observed = self._aware(raw, "observed_at")
        except (TypeError, ValueError):
            return False
        age = (cutoff - observed).total_seconds()
        return 0 <= age <= self.freshness_seconds

    @staticmethod
    def _safe_run(run: Mapping[str, Any]) -> dict[str, Any]:
        allowed = (
            "id",
            "pilot_id",
            "operation",
            "status",
            "outcome",
            "response_sha256",
            "response_byte_size",
            "record_count",
            "summary",
            "started_at",
            "completed_at",
            "raw_response_evidence_id",
            "raw_response_stored",
            "raw_response_verified",
            "error_code",
        )
        return {key: run.get(key) for key in allowed}

    @staticmethod
    def _scope(principal: Principal, entity_scope: Mapping[str, Any], store_ref: str) -> dict[str, Any]:
        status = str(entity_scope.get("status") or "")
        entity = str(entity_scope.get("entity_ref") or "").strip() if status == "ready" else ""
        authority = str(entity_scope.get("authority_sha256") or "").strip() if entity else ""
        return {
            "tenant_ref": principal.tenant_ref,
            "entity_ref": entity or None,
            "store_ref": str(store_ref).strip(),
            "scope_grant_authority_sha256": authority or None,
        }

    @staticmethod
    def _result(
        *,
        status: str,
        gate_status: str,
        scope: dict[str, Any],
        run: dict[str, Any] | None,
        checks: dict[str, bool],
        blockers: list[str],
        evidence_ids: list[str],
        source_contract: dict[str, Any] | None,
        runtime_identity: dict[str, Any] | None,
        next_action: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "contract_id": OzonProductionAcceptanceService.CONTRACT_ID,
            "contract_version": OzonProductionAcceptanceService.CONTRACT_VERSION,
            "status": status,
            "gate_status": gate_status,
            "accepted": status == "accepted",
            "scope": scope,
            "run": run,
            "checks": checks,
            "blockers": sorted(set(blockers)),
            "evidence_ids": sorted(set(evidence_ids)),
            "source_contract": source_contract,
            "runtime_identity": runtime_identity,
            "next_action": next_action,
            "external_write_allowed": False,
            "formal_fact_promotion_allowed": False,
            "production_release_allowed": False,
            "credential_values_returned": False,
        }
        payload["snapshot_sha256"] = OzonProductionAcceptanceService._hash(payload)
        return payload

    @staticmethod
    def _metadata(value: Any) -> dict[str, Any]:
        metadata = OzonProductionAcceptanceService._value(value, "metadata")
        return dict(metadata) if isinstance(metadata, Mapping) else {}

    @staticmethod
    def _grade(value: Any) -> str:
        grade = OzonProductionAcceptanceService._value(value, "grade")
        return getattr(grade, "value", str(grade))

    @staticmethod
    def _value(value: Any, key: str) -> Any:
        if isinstance(value, Mapping):
            return value.get(key)
        return getattr(value, key, None)

    @staticmethod
    def _aware(value: Any, name: str) -> datetime:
        if isinstance(value, datetime):
            parsed = value
        else:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{name} must include a timezone")
        return parsed.astimezone(UTC)

    @staticmethod
    def _required(value: Any, name: str, maximum: int) -> str:
        text = str(value or "").strip()
        if not text or len(text) > maximum or any(char in text for char in "\r\n\0"):
            raise OzonProductionAcceptanceError(f"{name} is invalid")
        return text

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()

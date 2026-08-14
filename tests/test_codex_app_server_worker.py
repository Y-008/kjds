from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import struct
import zlib
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import apps.control_plane.codex_app_server_worker as worker_module
from apps.control_plane.codex_app_server_worker import (
    CONTRACT_ID,
    EXPECTED_CONTRACT_CONTENT_SHA256,
    EXPECTED_FIXTURE_CONTENT_SHA256,
    EXPECTED_PROTOCOL_PINS,
    MAX_ARTIFACT_BYTES,
    MAX_BASE64_CHARS,
    MAX_PROTOCOL_CONTAINER_ITEMS,
    MAX_PROTOCOL_DEPTH,
    MAX_PROTOCOL_FIELD_CHARS,
    MAX_PROTOCOL_MESSAGES,
    MAX_PROTOCOL_METADATA_CHARS,
    CodexAppServerImageWorker,
    CodexImageWorkerContract,
    DurableDispatchClaim,
    DurableDispatchPeek,
    ImageWorkerRequest,
    ProtocolTransportDisconnected,
    RuntimeProtocolReceipt,
    TransportDescriptor,
    WorkerScope,
    WorkerTransition,
    canonical_json_sha256,
    sealed_transition_sha256,
)
from apps.control_plane.media_connectors import (
    MediaConnectorEventRow,
    MediaConnectorRegistry,
    MediaConnectorRow,
)
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base

NOW = datetime(2026, 8, 4, 8, tzinfo=UTC)
COMPLETED_AT_MS = 1_785_830_400_000
FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "media_agent"
    / "bas182_codex_app_server_image_worker_v1.json"
)
CONTRACT_PATH = (
    Path(__file__).parents[1]
    / "docs"
    / "project"
    / "registries"
    / "codex_app_server_image_worker_contracts.json"
)
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
FIXTURE_SHA256 = hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest()
PNG_BYTES = base64.b64decode(FIXTURE["synthetic_png_base64"])


def principal(
    tenant: str = "tenant-a",
    *,
    roles: frozenset[str] = frozenset({"operator"}),
) -> Principal:
    return Principal(
        actor_id=f"operator-{tenant}",
        roles=roles,
        tenant_ref=tenant,
    )


class FakeConnectorRegistry:
    def __init__(self) -> None:
        self.get_calls = 0
        self.eligible_calls = 0
        self.last_eligible_as_of: datetime | None = None
        self.get_error: Exception | None = None
        self.eligible_error: Exception | None = None
        self.descriptor = {
            "connector_ref": "mcn_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "derived_tenant_ref": "tenant-a",
            "provider": "codex_oauth",
            "deployment_mode": "customer_local",
            "binding_sha256": "a" * 64,
            "protocol_version": "codex-app-server/0.142.5",
            "capabilities": ["image_generation", "image_editing"],
            "health": "READY",
            "concurrency_limit": 1,
            "rate_limit_summary": None,
            "last_heartbeat_at": NOW.isoformat(),
            "created_at": (NOW - timedelta(days=1)).isoformat(),
            "revoked_at": None,
        }

    def get(self, *, principal: Principal, connector_ref: str) -> dict[str, Any]:
        self.get_calls += 1
        if self.get_error is not None:
            raise self.get_error
        if (
            principal.tenant_ref != self.descriptor["derived_tenant_ref"]
            or connector_ref != self.descriptor["connector_ref"]
        ):
            raise KeyError("not found")
        return {"connector": deepcopy(self.descriptor)}

    def require_eligible(
        self,
        *,
        tenant_ref: str,
        connector_ref: str,
        provider: str,
        required_capabilities: set[str],
        as_of: datetime,
    ) -> dict[str, Any]:
        self.eligible_calls += 1
        self.last_eligible_as_of = as_of
        if self.eligible_error is not None:
            raise self.eligible_error
        if (
            tenant_ref != self.descriptor["derived_tenant_ref"]
            or connector_ref != self.descriptor["connector_ref"]
            or provider != self.descriptor["provider"]
            or not required_capabilities.issubset(self.descriptor["capabilities"])
            or self.descriptor["health"] != "READY"
        ):
            raise PermissionError("not eligible")
        return {"connector": deepcopy(self.descriptor)}


class DurableStore:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.terminal_seals: set[str] = set()


class FakeDurablePort:
    def __init__(self, store: DurableStore) -> None:
        self.store = store
        self.peek_calls = 0
        self.claim_calls = 0
        self.reserve_count = 0
        self.record_calls = 0
        self.race_before_claim = False
        self.claim_mutator = None
        self.peek_error: Exception | None = None
        self.claim_error: Exception | None = None
        self.record_error: Exception | None = None
        self.dispatched_at_ms = COMPLETED_AT_MS - 1_000
        self.readback_deadline_ms = COMPLETED_AT_MS + 1_000

    @staticmethod
    def _key(tenant_ref: str, request: ImageWorkerRequest):
        return tenant_ref, request.job_ref, request.idempotency_key

    @staticmethod
    def _token(key: tuple[str, str, str], row: dict[str, Any] | None) -> str:
        return canonical_json_sha256(
            {
                "key": key,
                "exists": row is not None,
                "generation": row["generation"] if row else 0,
                "fingerprint": row["fingerprint"] if row else None,
            }
        )

    def peek(
        self,
        *,
        tenant_ref: str,
        connector_ref: str,
        request: ImageWorkerRequest,
        request_fingerprint_sha256: str,
    ) -> DurableDispatchPeek:
        self.peek_calls += 1
        if self.peek_error is not None:
            raise self.peek_error
        key = self._key(tenant_ref, request)
        row = self.store.rows.get(key)
        if row is not None and row["fingerprint"] != request_fingerprint_sha256:
            raise RuntimeError("idempotency drift")
        return DurableDispatchPeek(
            exists=row is not None,
            current_state=row["state"] if row else None,
            tenant_ref=tenant_ref,
            connector_ref=connector_ref,
            provider="codex_oauth",
            connector_binding_sha256=row["binding"] if row else None,
            runtime_protocol_authority_sha256=row["authority"] if row else None,
            request_fingerprint_sha256=request_fingerprint_sha256,
            peek_token_sha256=self._token(key, row),
            resume_readback_satisfied=row["resume_ready"] if row else False,
        )

    def claim(
        self,
        *,
        scope: WorkerScope,
        request: ImageWorkerRequest,
        request_fingerprint_sha256: str,
        expected_peek_token_sha256: str,
    ) -> DurableDispatchClaim:
        self.claim_calls += 1
        if self.claim_error is not None:
            raise self.claim_error
        key = self._key(scope.tenant_ref, request)
        row = self.store.rows.get(key)
        if self.race_before_claim:
            self.race_before_claim = False
            if row is None:
                self.store.rows[key] = {
                    "fingerprint": "f" * 64,
                    "state": "READY_TO_DISPATCH",
                    "resume_ready": False,
                    "transition": None,
                    "evidence_ref": None,
                    "binding": scope.connector_binding_sha256,
                    "authority": scope.runtime_protocol_authority_sha256,
                    "generation": 1,
                    "terminal_claim": None,
                }
            else:
                row["generation"] += 1
            row = self.store.rows.get(key)
        if self._token(key, row) != expected_peek_token_sha256:
            raise RuntimeError("durable peek token conflicted")
        if row is None:
            row = {
                "fingerprint": request_fingerprint_sha256,
                "state": "READY_TO_DISPATCH",
                "resume_ready": False,
                "transition": None,
                "evidence_ref": None,
                "binding": scope.connector_binding_sha256,
                "authority": scope.runtime_protocol_authority_sha256,
                "generation": 1,
                "terminal_claim": None,
            }
            self.store.rows[key] = row
            self.reserve_count += 1
        elif row["fingerprint"] != request_fingerprint_sha256:
            raise RuntimeError("idempotency drift")
        state = row["state"]
        if state in {"ARTIFACT_READY", "FAILED"}:
            action = "terminal"
        elif state == "UNKNOWN_OUTCOME":
            action = "readback"
        elif state in {"LOGIN_REQUIRED", "LIMITED"}:
            action = (
                "dispatch"
                if request.explicit_resume and row["resume_ready"]
                else "readback"
            )
        else:
            action = "dispatch"
        if action == "terminal":
            claim = row["terminal_claim"]
            if claim is None:
                raise RuntimeError("terminal claim missing")
            return self.claim_mutator(claim) if self.claim_mutator else claim
        claim = DurableDispatchClaim(
            dispatch_ref="dispatch_bas182_a",
            action=action,
            current_state=state,
            tenant_ref=scope.tenant_ref,
            connector_ref=scope.connector_ref,
            provider=scope.provider,
            connector_binding_sha256=scope.connector_binding_sha256,
            runtime_protocol_authority_sha256=(
                scope.runtime_protocol_authority_sha256
            ),
            request_fingerprint_sha256=request_fingerprint_sha256,
            thread_id=FIXTURE["identities"]["thread_id"],
            turn_id=FIXTURE["identities"]["turn_id"],
            item_id=FIXTURE["identities"]["item_id"],
            dispatched_at_ms=self.dispatched_at_ms,
            readback_deadline_ms=self.readback_deadline_ms,
            resume_readback_satisfied=row["resume_ready"],
            sealed_transition=None,
            sealed_transition_sha256=None,
            sealed_evidence_ref=None,
        )
        # The durable claim reserves a dispatch attempt before transport. A crash
        # therefore projects UNKNOWN_OUTCOME on the next process rather than dispatching.
        if action == "dispatch":
            row["state"] = "UNKNOWN_OUTCOME"
            row["generation"] += 1
        return self.claim_mutator(claim) if self.claim_mutator else claim

    def record(
        self,
        *,
        scope: WorkerScope,
        claim: DurableDispatchClaim,
        transition: WorkerTransition,
    ) -> str | None:
        self.record_calls += 1
        if self.record_error is not None:
            raise self.record_error
        row = next(
            value
            for value in self.store.rows.values()
            if value["fingerprint"] == claim.request_fingerprint_sha256
        )
        row["state"] = transition.state
        row["resume_ready"] = transition.resume_readback_satisfied
        row["transition"] = transition
        if transition.state == "ARTIFACT_READY":
            row["evidence_ref"] = "evd_" + "b" * 32
        row["generation"] += 1
        if transition.state in {"ARTIFACT_READY", "FAILED"}:
            terminal = replace(
                claim,
                action="terminal",
                current_state=transition.state,
                connector_binding_sha256=scope.connector_binding_sha256,
                runtime_protocol_authority_sha256=(
                    scope.runtime_protocol_authority_sha256
                ),
                resume_readback_satisfied=transition.resume_readback_satisfied,
                sealed_transition=transition,
                sealed_evidence_ref=row["evidence_ref"],
            )
            seal = sealed_transition_sha256(
                transition,
                claim=terminal,
                evidence_ref=row["evidence_ref"],
            )
            terminal = replace(terminal, sealed_transition_sha256=seal)
            row["terminal_claim"] = terminal
            self.store.terminal_seals.add(seal)
        return row["evidence_ref"]


class FakeTerminalAuthority:
    def __init__(self, store: DurableStore) -> None:
        self.store = store
        self.calls = 0
        self.raise_error: Exception | None = None

    def verify(self, **values: Any) -> None:
        self.calls += 1
        if self.raise_error is not None:
            raise self.raise_error
        seal = values["sealed_transition_sha256"]
        expected = sealed_transition_sha256(
            values["transition"],
            claim=values["claim"],
            evidence_ref=values["evidence_ref"],
        )
        if seal != expected or seal not in self.store.terminal_seals:
            raise PermissionError("terminal authority invalid")


class FakeRuntimeProtocolAuthority:
    def __init__(self) -> None:
        self.calls = 0
        self.last_receipt: RuntimeProtocolReceipt | None = None
        self.mutate_field: str | None = None
        self.raise_error: Exception | None = None
        self.overrides: dict[str, Any] = {}

    def verify(
        self,
        *,
        descriptor,
        connector_ref,
        checked_at,
        contract,
        transport_descriptor,
    ):
        del connector_ref
        self.calls += 1
        if self.raise_error is not None:
            raise self.raise_error
        authority_payload = {
            "connector_ref": descriptor["connector_ref"],
            "connector_binding_sha256": descriptor["binding_sha256"],
            "protocol_version": "codex-app-server/0.142.5",
            "codex_cli_version": "codex-cli 0.142.5",
            "aggregate_schema_canonical_sha256": contract.aggregate_schema_sha256,
            "item_completed_schema_canonical_sha256": contract.item_schema_sha256,
            "turn_completed_schema_canonical_sha256": contract.turn_schema_sha256,
            "canonical_bundle_sha256": EXPECTED_PROTOCOL_PINS[
                "canonical_bundle_observation_sha256"
            ],
            "actual_transport_kind": transport_descriptor.actual_transport_kind,
            "transport_adapter_version": transport_descriptor.adapter_version,
            "transport_adapter_sha256": transport_descriptor.adapter_sha256,
        }
        authority_sha = canonical_json_sha256(authority_payload)
        values = {
            **authority_payload,
            "authority_sha256": authority_sha,
            "checked_at": checked_at.isoformat(),
            "recorded_at": checked_at.isoformat(),
            "effective_at": (checked_at - timedelta(seconds=1)).isoformat(),
            "fresh_until": (checked_at + timedelta(minutes=5)).isoformat(),
        }
        for field, value in self.overrides.items():
            if field in authority_payload:
                authority_payload[field] = value
        authority_sha = canonical_json_sha256(authority_payload)
        temporal = {
            "checked_at": checked_at,
            "recorded_at": checked_at,
            "effective_at": checked_at - timedelta(seconds=1),
            "fresh_until": checked_at + timedelta(minutes=5),
        }
        for field, value in self.overrides.items():
            if field in temporal:
                temporal[field] = value
        values = {
            **authority_payload,
            "authority_sha256": authority_sha,
            **{field: value.isoformat() for field, value in temporal.items()},
        }
        receipt = RuntimeProtocolReceipt(
            **authority_payload,
            authority_sha256=authority_sha,
            **temporal,
            receipt_sha256=canonical_json_sha256(values),
        )
        if self.mutate_field:
            replacement: Any = "f" * 64
            if self.mutate_field in {
                "checked_at",
                "recorded_at",
                "effective_at",
                "fresh_until",
            }:
                replacement = checked_at + timedelta(hours=1)
            receipt = replace(receipt, **{self.mutate_field: replacement})
        self.last_receipt = receipt
        return receipt


class FakeTransport:
    def __init__(
        self,
        *,
        runtime_authority: FakeRuntimeProtocolAuthority | None = None,
        dispatch: list[Any] | None = None,
        readback: list[Any] | None = None,
        actual_transport_kind: str = "stdio",
        adapter_version: str = "test-adapter-v1",
        adapter_sha256: str = "9" * 64,
    ) -> None:
        self.runtime_authority = runtime_authority
        self.dispatch_results = list(dispatch or [])
        self.readback_results = list(readback or [])
        self.dispatch_calls = 0
        self.readback_calls = 0
        self.actual_transport_kind = actual_transport_kind
        self.adapter_version = adapter_version
        self.adapter_sha256 = adapter_sha256

    def descriptor(self) -> TransportDescriptor:
        return TransportDescriptor(
            actual_transport_kind=self.actual_transport_kind,
            adapter_version=self.adapter_version,
            adapter_sha256=self.adapter_sha256,
        )

    def dispatch(self, *, claim: DurableDispatchClaim, request: ImageWorkerRequest):
        del claim, request
        self.dispatch_calls += 1
        return self._next(self.dispatch_results)

    def readback(self, *, claim: DurableDispatchClaim):
        del claim
        self.readback_calls += 1
        return self._next(self.readback_results)

    def _next(self, values: list[Any]) -> Any:
        if not values:
            raise AssertionError("unexpected transport call")
        value = values.pop(0)
        if isinstance(value, BaseException):
            raise value
        if isinstance(value, dict):
            value = deepcopy(value)
            if self.runtime_authority is None or self.runtime_authority.last_receipt is None:
                raise AssertionError("runtime receipt was not issued")
            value.setdefault(
                "runtime_protocol_receipt_sha256",
                self.runtime_authority.last_receipt.receipt_sha256,
            )
        return value


def request(**changes: Any) -> ImageWorkerRequest:
    values = {
        "job_ref": "job_bas182_a",
        "tool_name": "media.image_generate",
        "idempotency_key": "idem_bas182_a",
        "request_sha256": "c" * 64,
        "data_as_of": NOW - timedelta(hours=1),
        "transport": "stdio",
        "protocol_version": "codex-app-server/0.142.5",
        "explicit_resume": False,
    }
    values.update(changes)
    return ImageWorkerRequest(**values)


def transcript(
    artifact: Path,
    *,
    revised_prompt: str = "synthetic prompt omitted",
) -> dict[str, Any]:
    messages = deepcopy(FIXTURE["success_transcript"])
    replacements = {
        "${PNG_BASE64}": FIXTURE["synthetic_png_base64"],
        "${ARTIFACT_PATH}": str(artifact.absolute()),
        "${IGNORED_REVISED_PROMPT}": revised_prompt,
    }

    def replace_placeholders(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: replace_placeholders(item) for key, item in value.items()}
        if isinstance(value, list):
            return [replace_placeholders(item) for item in value]
        return replacements.get(value, value)

    messages = replace_placeholders(messages)
    return {"messages": messages, "disconnected": False}


def handshake_only(extra: dict[str, Any]) -> dict[str, Any]:
    return {
        "messages": [*deepcopy(FIXTURE["success_transcript"][:3]), extra],
        "disconnected": False,
    }


def paused_transcript(info: Any) -> dict[str, Any]:
    messages = deepcopy(FIXTURE["success_transcript"][:4])
    turn = {
        "id": FIXTURE["identities"]["turn_id"],
        "items": [],
        "status": "failed",
        "itemsView": "full",
        "error": {
            "message": "provider-body-canary",
            "additionalDetails": "provider-id-canary",
            "codexErrorInfo": info,
        },
        "startedAt": (COMPLETED_AT_MS - 1_000) // 1000,
        "completedAt": COMPLETED_AT_MS // 1000,
        "durationMs": 1_000,
    }
    messages.append(
        {
            "direction": "server_notification",
            "method": "turn/completed",
            "params": {
                "threadId": FIXTURE["identities"]["thread_id"],
                "turn": turn,
            },
        }
    )
    return {"messages": messages, "disconnected": False}


def make_worker(
    tmp_path: Path,
    *,
    registry: FakeConnectorRegistry | None = None,
    store: DurableStore | None = None,
    transport: FakeTransport | None = None,
    clock=lambda: NOW,
    runtime_authority: FakeRuntimeProtocolAuthority | None = None,
):
    root = tmp_path / "artifacts"
    root.mkdir(exist_ok=True)
    registry = registry or FakeConnectorRegistry()
    store = store or DurableStore()
    port = FakeDurablePort(store)
    runtime_authority = runtime_authority or FakeRuntimeProtocolAuthority()
    if transport is None:
        transport = FakeTransport(runtime_authority=runtime_authority)
    else:
        transport.runtime_authority = runtime_authority
    terminal_authority = FakeTerminalAuthority(store)
    worker = CodexAppServerImageWorker(
        connector_registry=registry,
        dispatch_port=port,
        terminal_authority=terminal_authority,
        runtime_protocol_authority=runtime_authority,
        transport=transport,
        artifact_roots={registry.descriptor["connector_ref"]: root},
        clock=clock,
    )
    worker._test_terminal_authority = terminal_authority
    worker._test_runtime_authority = runtime_authority
    return worker, registry, store, port, transport, root


def write_png(root: Path, data: bytes = PNG_BYTES, name: str = "result.png") -> Path:
    path = root / name
    path.write_bytes(data)
    return path


def find_message(payload: dict[str, Any], method: str) -> dict[str, Any]:
    return next(item for item in payload["messages"] if item.get("method") == method)


def sync_completed_turn_item(payload: dict[str, Any]) -> None:
    completed = find_message(payload, "item/completed")["params"]["item"]
    turn = find_message(payload, "turn/completed")["params"]["turn"]
    turn["items"] = [deepcopy(completed)]


def png_chunk(kind: bytes, content: bytes) -> bytes:
    crc = zlib.crc32(kind)
    crc = zlib.crc32(content, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", crc)


def structural_png(width: int, height: int) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"IDAT", b"x")
        + png_chunk(b"IEND", b"")
    )


def indexed_png(*, bit_depth: int, palette_entries: int) -> bytes:
    ihdr = struct.pack(">IIBBBBB", 1, 1, bit_depth, 3, 0, 0, 0)
    scanline = b"\x00\x00"
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"PLTE", b"\x00\x00\x00" * palette_entries)
        + png_chunk(b"IDAT", zlib.compress(scanline))
        + png_chunk(b"IEND", b"")
    )


def assert_zero_authority(observation: dict[str, Any]) -> None:
    for field in (
        "fact_promoted",
        "finance_entry_persisted",
        "approval_granted",
        "permit_granted",
        "pilot_started",
        "outbox_emitted",
        "platform_write",
    ):
        assert observation[field] is False
    assert observation["automatic_provider_retry"] == 0
    assert observation["identity_rotation_count"] == 0
    assert observation["cross_scope_leakage_count"] == 0


def test_contract_and_fixture_freeze_canonical_json_semantics():
    contract = CodexImageWorkerContract()
    payload = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    fixture_without_hash = {k: v for k, v in FIXTURE.items() if k != "content_sha256"}

    assert contract.payload == payload
    assert contract.payload["contract_id"] == CONTRACT_ID
    assert contract.sha256 == EXPECTED_CONTRACT_CONTENT_SHA256
    assert contract.fixture_sha256 == EXPECTED_FIXTURE_CONTENT_SHA256
    assert contract.aggregate_schema_sha256 == "064f4e66" + (
        "f3f9efa34601039e80e1c57a5593fdd77bad7a6562ec014cf7452dc2"
    )
    assert FIXTURE["content_sha256"] == canonical_json_sha256(
        fixture_without_hash
    )
    assert canonical_json_sha256('{"b":2,"a":1}') == canonical_json_sha256(
        '{\n  "a": 1, "b": 2\n}'
    )
    assert payload["protocol_pin"]["raw_aggregate_sha256_is_authoritative"] is False
    assert payload["image_item_contract"]["started_state"]["status"] == "in_progress"
    assert payload["artifact_contract"]["full_pixel_decode_claimed"] is False
    assert payload["scope_contract"]["dispatch_roles"] == ["admin", "operator"]
    assert payload["scope_contract"]["readback_roles"] == ["admin", "operator"]
    assert payload["scope_contract"]["role_check_before_durable_peek"] is True
    assert payload["transports"]["selection_authority"] == (
        "server_owned_transport_descriptor"
    )
    assert payload["transports"]["runtime_receipt_binding_required"] is True
    assert payload["transports"]["descriptor_revalidated_before_durable_peek"] is True
    assert payload["protocol_budget"] == {
        "maximum_message_count": MAX_PROTOCOL_MESSAGES,
        "maximum_non_artifact_field_characters": MAX_PROTOCOL_FIELD_CHARS,
        "maximum_non_artifact_aggregate_characters": MAX_PROTOCOL_METADATA_CHARS,
        "maximum_container_items": MAX_PROTOCOL_CONTAINER_ITEMS,
        "maximum_depth": MAX_PROTOCOL_DEPTH,
        "maximum_base64_characters": MAX_BASE64_CHARS,
        "integer_range": "signed_int64",
        "nonfinite_float_allowed": False,
        "budget_enforced_before_canonical_hash_and_artifact_io": True,
        "event_chain_projection": "bounded_redacted_protocol_projection_v1",
    }
    assert all("rust-v0.142.5" in item["url"] for item in payload["official_evidence"])
    turn_source = next(
        item
        for item in payload["official_evidence"]
        if item["url"].endswith("/protocol/v2/thread_data.rs")
    )
    assert turn_source == {
        "url": "https://github.com/openai/codex/blob/rust-v0.142.5/"
        "codex-rs/app-server-protocol/src/protocol/v2/thread_data.rs",
        "sha256": "f6dd5ece89cdecfc0f5644bf37a2bc9a956b34394f85d049a9336a63c62d7665",
        "locator": "lines 188-206: Turn startedAt/completedAt Unix seconds "
        "and durationMs milliseconds",
    }
    revoked_case = next(
        item
        for item in FIXTURE["negative_cases"]
        if item["case_id"] == "connector-current-revoked"
    )
    assert revoked_case["reason"] == "connector_not_currently_eligible"


def test_repository_contract_reformat_is_semantic_but_resealed_drift_is_rejected(
    tmp_path, monkeypatch
):
    contract_copy = tmp_path / "contract.json"
    fixture_copy = tmp_path / "fixture.json"
    shutil.copyfile(CONTRACT_PATH, contract_copy)
    shutil.copyfile(FIXTURE_PATH, fixture_copy)
    contract_payload = json.loads(contract_copy.read_text(encoding="utf-8"))
    fixture_payload = json.loads(fixture_copy.read_text(encoding="utf-8"))
    contract_copy.write_text(
        json.dumps(contract_payload, separators=(",", ":")), encoding="utf-8"
    )
    fixture_copy.write_text(
        json.dumps(fixture_payload, sort_keys=True, indent=4), encoding="utf-8"
    )
    monkeypatch.setattr(worker_module, "CONTRACT_PATH", contract_copy)
    monkeypatch.setattr(worker_module, "FIXTURE_PATH", fixture_copy)

    reformatted = CodexImageWorkerContract()
    assert reformatted.sha256 == EXPECTED_CONTRACT_CONTENT_SHA256
    assert reformatted.fixture_sha256 == EXPECTED_FIXTURE_CONTENT_SHA256

    fixture_payload["codex_cli_version"] = "codex-cli 0.142.6"
    fixture_body = {
        key: value for key, value in fixture_payload.items() if key != "content_sha256"
    }
    fixture_payload["content_sha256"] = canonical_json_sha256(fixture_body)
    fixture_copy.write_text(json.dumps(fixture_payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="fixture seal drifted"):
        CodexImageWorkerContract()


@pytest.mark.parametrize(
    "roles",
    [
        frozenset(),
        frozenset({"reviewer"}),
        frozenset({"compliance"}),
        frozenset({"monitor"}),
        frozenset({"approver"}),
        frozenset({"risk"}),
        frozenset({"pilot_reader"}),
        frozenset({"executor"}),
    ],
)
def test_non_execution_roles_are_blocked_before_peek_claim_or_transport(
    tmp_path, roles
):
    worker, registry, store, port, transport_port, _ = make_worker(tmp_path)
    actor = principal(roles=roles)

    result = worker.run(
        principal=actor,
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert result["state"] == "BLOCKED"
    assert result["safe_reason_code"] == "principal_role_not_authorized"
    assert port.peek_calls == 0
    assert port.claim_calls == 0
    assert port.record_calls == 0
    assert store.rows == {}
    assert registry.get_calls == 0
    assert registry.eligible_calls == 0
    assert transport_port.dispatch_calls == 0
    assert transport_port.readback_calls == 0


@pytest.mark.parametrize("role", ["operator", "admin"])
def test_explicit_execution_roles_can_dispatch(tmp_path, role):
    worker, registry, _, port, transport_port, root = make_worker(tmp_path)
    artifact = write_png(root)
    transport_port.dispatch_results.append(transcript(artifact))

    result = worker.run(
        principal=principal(roles=frozenset({role})),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert result["state"] == "ARTIFACT_READY"
    assert port.peek_calls == 2
    assert port.claim_calls == 2
    assert transport_port.dispatch_calls == 1


def test_real_media_connector_registry_cannot_bypass_worker_role_policy(tmp_path):
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[MediaConnectorRow.__table__, MediaConnectorEventRow.__table__],
    )
    registry = MediaConnectorRegistry(engine=engine, clock=lambda: NOW)
    admin = Principal("admin-a", frozenset({"admin"}), "tenant-a")
    connector = registry.register(
        principal=admin,
        provider="codex_oauth",
        deployment_mode="customer_local",
        protocol_version="codex-app-server/0.142.5",
        capabilities=["image_generation", "image_editing"],
        concurrency_limit=1,
        idempotency_key="bas182-real-register",
    )["connector"]
    registry.observe(
        principal=Principal("monitor-a", frozenset({"monitor"}), "tenant-a"),
        connector_ref=connector["connector_ref"],
        health="READY",
        observed_at=NOW,
        rate_limit_status="ok",
        rate_limit_observed_at=NOW,
        retry_after_at=None,
        idempotency_key="bas182-real-ready",
    )
    store = DurableStore()
    port = FakeDurablePort(store)
    runtime_authority = FakeRuntimeProtocolAuthority()
    transport_port = FakeTransport(runtime_authority=runtime_authority)
    root = tmp_path / "real-registry-artifacts"
    root.mkdir()
    worker = CodexAppServerImageWorker(
        connector_registry=registry,
        dispatch_port=port,
        terminal_authority=FakeTerminalAuthority(store),
        runtime_protocol_authority=runtime_authority,
        transport=transport_port,
        artifact_roots={connector["connector_ref"]: root},
        clock=lambda: NOW,
    )

    rejected = worker.run(
        principal=Principal("reviewer-a", frozenset({"reviewer"}), "tenant-a"),
        connector_ref=connector["connector_ref"],
        request=request(),
    ).as_dict()
    assert (rejected["state"], rejected["safe_reason_code"]) == (
        "BLOCKED",
        "principal_role_not_authorized",
    )
    assert port.peek_calls == port.claim_calls == 0
    assert transport_port.dispatch_calls == transport_port.readback_calls == 0

    artifact = write_png(root)
    transport_port.dispatch_results.append(transcript(artifact))
    admitted = worker.run(
        principal=Principal("operator-a", frozenset({"operator"}), "tenant-a"),
        connector_ref=connector["connector_ref"],
        request=request(),
    ).as_dict()
    assert admitted["state"] == "ARTIFACT_READY"
    assert port.reserve_count == 1
    assert transport_port.dispatch_calls == 1


def test_real_registry_pause_readback_ready_resume_and_revoke_are_current(
    tmp_path,
):
    now = [NOW]
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[MediaConnectorRow.__table__, MediaConnectorEventRow.__table__],
    )
    registry = MediaConnectorRegistry(engine=engine, clock=lambda: now[0])
    admin = Principal("admin-a", frozenset({"admin"}), "tenant-a")
    operator = Principal("operator-a", frozenset({"operator"}), "tenant-a")
    monitor = Principal("monitor-a", frozenset({"monitor"}), "tenant-a")
    connector = registry.register(
        principal=admin,
        provider="codex_oauth",
        deployment_mode="customer_local",
        protocol_version="codex-app-server/0.142.5",
        capabilities=["image_generation", "image_editing"],
        concurrency_limit=1,
        idempotency_key="bas182-pause-register",
    )["connector"]
    registry.observe(
        principal=monitor,
        connector_ref=connector["connector_ref"],
        health="READY",
        observed_at=now[0],
        rate_limit_status="ok",
        rate_limit_observed_at=now[0],
        retry_after_at=None,
        idempotency_key="bas182-pause-ready-1",
    )
    store = DurableStore()
    port = FakeDurablePort(store)
    runtime_authority = FakeRuntimeProtocolAuthority()
    still_paused = handshake_only(
        {
            "direction": "server_notification",
            "method": "account/updated",
            "params": {"authMode": "none", "planType": None},
        }
    )
    now_ready = handshake_only(
        {
            "direction": "server_notification",
            "method": "account/updated",
            "params": {"authMode": "chatgpt", "planType": "plus"},
        }
    )
    transport_port = FakeTransport(
        runtime_authority=runtime_authority,
        dispatch=[paused_transcript("unauthorized")],
        readback=[still_paused, now_ready],
    )
    root = tmp_path / "real-pause-artifacts"
    root.mkdir()
    worker = CodexAppServerImageWorker(
        connector_registry=registry,
        dispatch_port=port,
        terminal_authority=FakeTerminalAuthority(store),
        runtime_protocol_authority=runtime_authority,
        transport=transport_port,
        artifact_roots={connector["connector_ref"]: root},
        clock=lambda: now[0],
    )
    first = worker.run(
        principal=operator,
        connector_ref=connector["connector_ref"],
        request=request(),
    ).as_dict()

    now[0] += timedelta(seconds=1)
    registry.observe(
        principal=monitor,
        connector_ref=connector["connector_ref"],
        health="LOGIN_REQUIRED",
        observed_at=now[0],
        rate_limit_status=None,
        rate_limit_observed_at=None,
        retry_after_at=None,
        idempotency_key="bas182-pause-login",
    )
    second = worker.run(
        principal=operator,
        connector_ref=connector["connector_ref"],
        request=request(),
    ).as_dict()

    now[0] += timedelta(seconds=1)
    registry.observe(
        principal=monitor,
        connector_ref=connector["connector_ref"],
        health="READY",
        observed_at=now[0],
        rate_limit_status="ok",
        rate_limit_observed_at=now[0],
        retry_after_at=None,
        idempotency_key="bas182-pause-ready-2",
    )
    third = worker.run(
        principal=operator,
        connector_ref=connector["connector_ref"],
        request=request(),
    ).as_dict()
    transport_port.dispatch_results.append(transcript(write_png(root)))
    fourth = worker.run(
        principal=operator,
        connector_ref=connector["connector_ref"],
        request=request(explicit_resume=True),
    ).as_dict()

    assert (first["state"], second["state"], third["state"], fourth["state"]) == (
        "LOGIN_REQUIRED",
        "LOGIN_REQUIRED",
        "LOGIN_REQUIRED",
        "ARTIFACT_READY",
    )
    assert second["safe_reason_code"] == "login_required"
    assert third["safe_reason_code"] == "fresh_readback_requires_explicit_resume"
    assert transport_port.dispatch_calls == 2
    assert transport_port.readback_calls == 2

    now[0] += timedelta(seconds=1)
    registry.revoke(
        principal=admin,
        connector_ref=connector["connector_ref"],
        observed_at=now[0],
        idempotency_key="bas182-pause-revoke",
    )
    fresh_store = DurableStore()
    fresh_port = FakeDurablePort(fresh_store)
    revoked_worker = CodexAppServerImageWorker(
        connector_registry=registry,
        dispatch_port=fresh_port,
        terminal_authority=FakeTerminalAuthority(fresh_store),
        runtime_protocol_authority=FakeRuntimeProtocolAuthority(),
        transport=FakeTransport(),
        artifact_roots={connector["connector_ref"]: root},
        clock=lambda: now[0],
    )
    revoked = revoked_worker.run(
        principal=operator,
        connector_ref=connector["connector_ref"],
        request=request(job_ref="job_revoked", idempotency_key="idem_revoked"),
    ).as_dict()
    assert (revoked["state"], revoked["safe_reason_code"]) == (
        "BLOCKED",
        "connector_not_currently_eligible",
    )
    assert fresh_port.peek_calls == 1
    assert fresh_port.claim_calls == fresh_port.reserve_count == 0


@pytest.mark.parametrize(
    "field",
    [
        "authority_sha256",
        "receipt_sha256",
        "connector_ref",
        "connector_binding_sha256",
        "protocol_version",
        "codex_cli_version",
        "aggregate_schema_canonical_sha256",
        "item_completed_schema_canonical_sha256",
        "turn_completed_schema_canonical_sha256",
        "canonical_bundle_sha256",
        "actual_transport_kind",
        "transport_adapter_version",
        "transport_adapter_sha256",
        "checked_at",
        "recorded_at",
        "effective_at",
        "fresh_until",
    ],
)
def test_runtime_protocol_receipt_field_drift_blocks_before_claim_or_transport(
    tmp_path, field
):
    authority = FakeRuntimeProtocolAuthority()
    authority.mutate_field = field
    worker, registry, _, port, transport_port, _ = make_worker(
        tmp_path, runtime_authority=authority
    )

    result = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert result["state"] == "BLOCKED"
    assert result["safe_reason_code"] == "connector_not_currently_eligible"
    assert port.peek_calls == 1
    assert port.claim_calls == 0
    assert port.record_calls == 0
    assert transport_port.dispatch_calls == transport_port.readback_calls == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("checked_at", NOW + timedelta(seconds=1)),
        ("recorded_at", NOW + timedelta(seconds=1)),
        ("effective_at", NOW + timedelta(seconds=1)),
        ("fresh_until", NOW - timedelta(seconds=1)),
        ("fresh_until", NOW + timedelta(minutes=6)),
    ],
)
def test_runtime_protocol_receipt_resealed_stale_or_future_windows_are_rejected(
    tmp_path, field, value
):
    authority = FakeRuntimeProtocolAuthority()
    authority.overrides[field] = value
    worker, registry, _, port, transport_port, _ = make_worker(
        tmp_path, runtime_authority=authority
    )

    result = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert result["state"] == "BLOCKED"
    assert port.claim_calls == 0
    assert transport_port.dispatch_calls == transport_port.readback_calls == 0


def test_runtime_current_receipt_clock_progress_keeps_stable_terminal_authority(
    tmp_path,
):
    registry = FakeConnectorRegistry()
    store = DurableStore()
    first_worker, _, _, _, first_transport, root = make_worker(
        tmp_path,
        registry=registry,
        store=store,
        clock=lambda: NOW,
    )
    first_transport.dispatch_results.append(transcript(write_png(root)))
    first = first_worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    later_worker, _, _, later_port, later_transport, _ = make_worker(
        tmp_path,
        registry=registry,
        store=store,
        clock=lambda: NOW + timedelta(minutes=2),
    )
    replay = later_worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert first["state"] == replay["state"] == "ARTIFACT_READY"
    assert later_port.claim_calls == 1
    assert later_transport.dispatch_calls == later_transport.readback_calls == 0


def test_runtime_stable_authority_rotation_blocks_existing_claim_before_claim(
    tmp_path,
):
    registry = FakeConnectorRegistry()
    store = DurableStore()
    first_worker, _, _, _, first_transport, root = make_worker(
        tmp_path, registry=registry, store=store
    )
    first_transport.dispatch_results.append(transcript(write_png(root)))
    first_worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    )

    rotated_authority = FakeRuntimeProtocolAuthority()
    rotated_authority.overrides["canonical_bundle_sha256"] = "d" * 64
    rotated_worker, _, _, rotated_port, rotated_transport, _ = make_worker(
        tmp_path,
        registry=registry,
        store=store,
        runtime_authority=rotated_authority,
        clock=lambda: NOW + timedelta(minutes=1),
    )
    blocked = rotated_worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert (blocked["state"], blocked["safe_reason_code"]) == (
        "BLOCKED",
        "connector_binding_invalid",
    )
    assert rotated_port.peek_calls == 1
    assert rotated_port.claim_calls == 0
    assert rotated_transport.dispatch_calls == rotated_transport.readback_calls == 0


def test_atomic_claim_rejects_peek_token_race_without_local_dispatch(tmp_path):
    worker, registry, store, port, transport_port, _ = make_worker(tmp_path)
    port.race_before_claim = True

    result = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert (result["state"], result["safe_reason_code"]) == (
        "BLOCKED",
        "durable_claim_invalid",
    )
    assert port.peek_calls == 1
    assert port.claim_calls == 1
    assert port.reserve_count == 0
    assert port.record_calls == 0
    assert len(store.rows) == 1  # the simulated external race winner only
    assert transport_port.dispatch_calls == transport_port.readback_calls == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"current_state": "LOGIN_REQUIRED", "resume_readback_satisfied": True},
        {"current_state": "LIMITED"},
        {"resume_readback_satisfied": True},
    ],
)
def test_new_claim_must_match_missing_peek_snapshot_before_transport(
    tmp_path, changes
):
    worker, registry, _, port, transport_port, _ = make_worker(tmp_path)
    port.claim_mutator = lambda claim: replace(claim, **changes)

    result = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert (result["state"], result["safe_reason_code"]) == (
        "BLOCKED",
        "durable_claim_invalid",
    )
    assert port.peek_calls == port.claim_calls == 1
    assert port.record_calls == 0
    assert transport_port.dispatch_calls == transport_port.readback_calls == 0


def test_paused_claim_state_and_resume_flag_must_match_existing_peek(tmp_path):
    registry = FakeConnectorRegistry()
    store = DurableStore()
    transport_port = FakeTransport(dispatch=[paused_transcript("unauthorized")])
    worker, _, _, port, _, _ = make_worker(
        tmp_path, registry=registry, store=store, transport=transport_port
    )
    first = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()
    assert first["state"] == "LOGIN_REQUIRED"
    port.claim_mutator = lambda claim: replace(
        claim,
        current_state="LIMITED",
        resume_readback_satisfied=not claim.resume_readback_satisfied,
    )

    drift = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert (drift["state"], drift["safe_reason_code"]) == (
        "BLOCKED",
        "durable_claim_invalid",
    )
    assert transport_port.dispatch_calls == 1
    assert transport_port.readback_calls == 0


def test_terminal_claim_state_cannot_be_interchanged_after_peek(tmp_path):
    worker, registry, _, port, transport_port, root = make_worker(tmp_path)
    transport_port.dispatch_results.append(transcript(write_png(root)))
    first = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()
    assert first["state"] == "ARTIFACT_READY"
    port.claim_mutator = lambda claim: replace(claim, current_state="FAILED")

    replay = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert (replay["state"], replay["safe_reason_code"]) == (
        "BLOCKED",
        "durable_claim_invalid",
    )
    assert transport_port.dispatch_calls == 1
    assert transport_port.readback_calls == 0


def test_success_validates_authoritative_item_and_returns_safe_receipt(tmp_path):
    worker, registry, _, _, transport_port, root = make_worker(tmp_path)
    artifact = write_png(root)
    transport_port.dispatch_results.append(transcript(artifact))

    result = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert result["state"] == "ARTIFACT_READY"
    assert result["safe_reason_code"] == "artifact_verified"
    assert result["artifact"] == {
        "sha256": hashlib.sha256(PNG_BYTES).hexdigest(),
        "bytes": len(PNG_BYTES),
        "mime_type": "image/png",
        "width": 1,
        "height": 1,
        "evidence_ref": "evd_" + "b" * 32,
    }
    assert result["protocol_dispatch_attempt_count"] == 1
    assert result["protocol_readback_attempt_count"] == 0
    assert registry.last_eligible_as_of == NOW
    assert "savedPath" not in json.dumps(result)
    assert "revisedPrompt" not in json.dumps(result)
    assert_zero_authority(result)


def test_terminal_replay_uses_sealed_projection_without_file_or_provider(tmp_path):
    worker, registry, store, _, transport_port, root = make_worker(tmp_path)
    artifact = write_png(root)
    transport_port.dispatch_results.append(transcript(artifact))
    first = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()
    artifact.unlink()

    replay_transport = FakeTransport()
    replay_worker, _, _, _, _, _ = make_worker(
        tmp_path,
        registry=registry,
        store=store,
        transport=replay_transport,
    )
    replay = replay_worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert replay["state"] == "ARTIFACT_READY"
    assert replay["artifact"] == first["artifact"]
    assert replay["projection_sha256"] == first["projection_sha256"]
    assert replay["protocol_dispatch_attempt_count"] == 0
    assert replay["protocol_readback_attempt_count"] == 0
    assert replay_transport.dispatch_calls == replay_transport.readback_calls == 0


def test_known_terminal_failure_is_not_an_artifact(tmp_path):
    worker, registry, _, _, transport_port, root = make_worker(tmp_path)
    artifact = write_png(root)
    payload = transcript(artifact)
    item = find_message(payload, "item/completed")["params"]["item"]
    item.update(status="failed", result="", revisedPrompt="synthetic failure")
    item.pop("savedPath")
    turn = find_message(payload, "turn/completed")["params"]["turn"]
    turn.update(
        status="failed",
        error={"message": "redacted", "codexErrorInfo": "other"},
    )
    sync_completed_turn_item(payload)
    transport_port.dispatch_results.append(payload)

    result = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert result["state"] == "FAILED"
    assert result["safe_reason_code"] == "image_generation_failed"
    assert result["artifact"] is None


@pytest.mark.parametrize("revised_prompt", ["paint a blue whale", None])
def test_official_failure_revised_prompt_is_accepted_but_never_projected(
    tmp_path, revised_prompt
):
    worker, registry, _, _, transport_port, root = make_worker(tmp_path)
    payload = transcript(write_png(root))
    item = find_message(payload, "item/completed")["params"]["item"]
    item.update(status="failed", result="", revisedPrompt=revised_prompt)
    item.pop("savedPath")
    turn = find_message(payload, "turn/completed")["params"]["turn"]
    turn.update(
        status="failed",
        error={"message": "safe fixture", "codexErrorInfo": "other"},
    )
    sync_completed_turn_item(payload)
    transport_port.dispatch_results.append(payload)

    result = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert (result["state"], result["safe_reason_code"]) == (
        "FAILED",
        "image_generation_failed",
    )
    assert "revisedPrompt" not in json.dumps(result)


@pytest.mark.parametrize(
    "error",
    [
        {},
        None,
        {"message": 7},
        {"message": "x", "unknown": "x"},
        {"message": "x", "additionalDetails": 7},
        {"message": "x", "codexErrorInfo": "not-a-schema-value"},
        {"message": "x", "codexErrorInfo": {"responseStreamConnectionFailed": {"httpStatusCode": True}}},
    ],
)
def test_failed_turn_requires_schema_valid_minimal_turn_error(tmp_path, error):
    worker, registry, _, _, transport_port, root = make_worker(tmp_path)
    payload = transcript(write_png(root))
    item = find_message(payload, "item/completed")["params"]["item"]
    item.update(status="failed", result="", revisedPrompt=None)
    item.pop("savedPath")
    turn = find_message(payload, "turn/completed")["params"]["turn"]
    turn.update(status="failed", error=error)
    sync_completed_turn_item(payload)
    transport_port.dispatch_results.append(payload)

    result = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert result["state"] == "UNKNOWN_OUTCOME"
    assert result["safe_reason_code"] == "protocol_event_malformed"


def test_completed_turn_rejects_empty_error_object(tmp_path):
    worker, registry, _, _, transport_port, root = make_worker(tmp_path)
    payload = transcript(write_png(root))
    find_message(payload, "turn/completed")["params"]["turn"]["error"] = {}
    transport_port.dispatch_results.append(payload)

    result = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert (result["state"], result["safe_reason_code"]) == (
        "UNKNOWN_OUTCOME",
        "protocol_event_malformed",
    )


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("server_version", "protocol_pin_mismatch"),
        ("started_camel_case", "protocol_event_malformed"),
        ("unknown_status", "image_item_terminal_semantics_unknown"),
        ("result_not_base64", "image_item_terminal_semantics_unknown"),
        ("saved_path_null", "artifact_path_missing"),
        ("wrong_thread", "protocol_identity_mismatch"),
        ("wrong_turn", "protocol_identity_mismatch"),
        ("wrong_item", "protocol_identity_mismatch"),
        ("wrong_completed_at", "protocol_completion_time_invalid"),
        ("unknown_item_field", "protocol_event_unknown"),
        ("unknown_thread_item", "protocol_identity_mismatch"),
        ("turn_failed_after_artifact", "turn_failed_after_artifact"),
    ],
)
def test_protocol_and_terminal_semantics_fail_closed(tmp_path, mutation, reason):
    worker, registry, _, _, transport_port, root = make_worker(tmp_path)
    artifact = write_png(root)
    payload = transcript(artifact)
    started = find_message(payload, "item/started")["params"]["item"]
    completed_message = find_message(payload, "item/completed")
    completed = completed_message["params"]["item"]
    turn = find_message(payload, "turn/completed")["params"]["turn"]
    if mutation == "server_version":
        payload["messages"][1]["result"]["serverInfo"]["version"] = "0.142.6"
    elif mutation == "started_camel_case":
        started["status"] = "inProgress"
    elif mutation == "unknown_status":
        completed["status"] = "done"
    elif mutation == "result_not_base64":
        completed["result"] = "not base64!"
    elif mutation == "saved_path_null":
        completed["savedPath"] = None
    elif mutation == "wrong_thread":
        completed_message["params"]["threadId"] = "thread_other"
    elif mutation == "wrong_turn":
        completed_message["params"]["turnId"] = "turn_other"
    elif mutation == "wrong_item":
        completed["id"] = "image_other"
    elif mutation == "wrong_completed_at":
        completed_message["params"]["completedAtMs"] = COMPLETED_AT_MS + 2_000
    elif mutation == "unknown_item_field":
        completed["providerRequestId"] = "secret-provider-id"
    elif mutation == "unknown_thread_item":
        started["type"] = "agentMessage"
    elif mutation == "turn_failed_after_artifact":
        turn.update(
            status="failed",
            error={"message": "secret backend body", "codexErrorInfo": "other"},
        )
    sync_completed_turn_item(payload)
    transport_port.dispatch_results.append(payload)

    result = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert result["state"] == "UNKNOWN_OUTCOME"
    assert result["safe_reason_code"] == reason
    assert result["artifact"] is None
    assert "secret" not in json.dumps(result).lower()


def test_turn_completion_without_image_item_and_duplicate_order_fail(tmp_path):
    worker, registry, _, _, transport_port, root = make_worker(tmp_path)
    artifact = write_png(root)
    missing = transcript(artifact)
    missing["messages"] = [
        item
        for item in missing["messages"]
        if item.get("method") not in {"item/started", "item/completed"}
    ]
    find_message(missing, "turn/completed")["params"]["turn"]["items"] = []
    duplicate = transcript(artifact)
    duplicate["messages"].insert(6, deepcopy(duplicate["messages"][5]))
    transport_port.dispatch_results.extend([missing, duplicate])

    first = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(job_ref="job_missing", idempotency_key="idem_missing"),
    ).as_dict()
    second = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(job_ref="job_duplicate", idempotency_key="idem_duplicate"),
    ).as_dict()

    assert (first["state"], first["safe_reason_code"]) == (
        "UNKNOWN_OUTCOME",
        "image_item_missing",
    )
    assert (second["state"], second["safe_reason_code"]) == (
        "UNKNOWN_OUTCOME",
        "protocol_event_out_of_order",
    )


@pytest.mark.parametrize("kind", ["outside", "traversal", "symlink"])
def test_artifact_path_must_remain_in_non_reparse_connector_root(tmp_path, kind):
    worker, registry, _, _, transport_port, root = make_worker(tmp_path)
    if kind == "outside":
        artifact = write_png(tmp_path, name="outside.png")
    elif kind == "traversal":
        artifact = write_png(root)
    else:
        target = write_png(root, name="target.png")
        artifact = root / "linked.png"
        try:
            os.symlink(target, artifact)
        except OSError as exc:
            pytest.skip(f"symlink creation is unavailable: {type(exc).__name__}")
    payload = transcript(artifact)
    if kind == "traversal":
        saved = str(root.resolve() / "subdir" / ".." / artifact.name)
        find_message(payload, "item/completed")["params"]["item"]["savedPath"] = saved
        sync_completed_turn_item(payload)
    transport_port.dispatch_results.append(payload)

    result = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert result["state"] == "UNKNOWN_OUTCOME"
    expected = (
        "artifact_symlink_or_reparse"
        if kind == "symlink"
        else "artifact_path_not_admitted"
    )
    assert result["safe_reason_code"] == expected


def test_open_root_handle_rejects_root_rename_and_replacement_race(tmp_path):
    worker, registry, _, _, transport_port, root = make_worker(tmp_path)
    artifact = write_png(root)
    payload = transcript(artifact)
    original_check = worker._reject_reparse_chain
    moved_root = tmp_path / "moved-original-root"

    def swap_root_after_check(checked_root: Path, checked_target: Path) -> None:
        original_check(checked_root, checked_target)
        checked_root.rename(moved_root)
        checked_root.mkdir()
        (checked_root / checked_target.name).write_bytes(PNG_BYTES)

    worker._reject_reparse_chain = swap_root_after_check
    transport_port.dispatch_results.append(payload)

    result = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert (result["state"], result["safe_reason_code"]) == (
        "UNKNOWN_OUTCOME",
        "artifact_path_not_admitted",
    )
    assert result["artifact"] is None


def test_open_file_handle_rejects_intermediate_symlink_swap_after_path_check(
    tmp_path,
):
    worker, registry, _, _, transport_port, root = make_worker(tmp_path)
    inner = root / "inner"
    inner.mkdir()
    artifact = write_png(inner)
    payload = transcript(artifact)
    outside = tmp_path / "outside-directory"
    outside.mkdir()
    write_png(outside)
    original_check = worker._reject_reparse_chain

    def swap_intermediate_after_check(
        checked_root: Path, checked_target: Path
    ) -> None:
        original_check(checked_root, checked_target)
        inner.rename(root / "original-inner")
        os.symlink(outside, inner, target_is_directory=True)

    worker._reject_reparse_chain = swap_intermediate_after_check
    transport_port.dispatch_results.append(payload)

    result = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert (result["state"], result["safe_reason_code"]) == (
        "UNKNOWN_OUTCOME",
        "artifact_path_not_admitted",
    )
    assert result["artifact"] is None


@pytest.mark.parametrize("kind", ["truncated", "missing_iend", "crc", "pixels"])
def test_png_structure_crc_terminal_and_pixel_bounds(tmp_path, kind):
    worker, registry, _, _, transport_port, root = make_worker(tmp_path)
    if kind == "truncated":
        data = PNG_BYTES[:-5]
    elif kind == "missing_iend":
        data = PNG_BYTES[:-12]
    elif kind == "crc":
        changed = bytearray(PNG_BYTES)
        changed[29] ^= 1
        data = bytes(changed)
    else:
        data = structural_png(10_000, 10_000)
    artifact = write_png(root, data)
    payload = transcript(artifact)
    find_message(payload, "item/completed")["params"]["item"]["result"] = (
        base64.b64encode(data).decode()
    )
    sync_completed_turn_item(payload)
    transport_port.dispatch_results.append(payload)

    result = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert result["state"] == "UNKNOWN_OUTCOME"
    assert result["safe_reason_code"] == "artifact_format_invalid"


@pytest.mark.parametrize(
    "data",
    [
        PNG_BYTES[:33] + png_chunk(b"ABCD", b"") + PNG_BYTES[33:],
        PNG_BYTES[:33] + png_chunk(b"abca", b"") + PNG_BYTES[33:],
        PNG_BYTES[:33] + png_chunk(b"a1CD", b"") + PNG_BYTES[33:],
        indexed_png(bit_depth=1, palette_entries=3),
    ],
)
def test_png_rejects_unknown_critical_reserved_bit_and_palette_overflow(
    tmp_path, data
):
    worker, registry, _, _, transport_port, root = make_worker(tmp_path)
    artifact = write_png(root, data)
    payload = transcript(artifact)
    find_message(payload, "item/completed")["params"]["item"]["result"] = (
        base64.b64encode(data).decode()
    )
    sync_completed_turn_item(payload)
    transport_port.dispatch_results.append(payload)

    result = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert (result["state"], result["safe_reason_code"]) == (
        "UNKNOWN_OUTCOME",
        "artifact_format_invalid",
    )


def test_png_allows_well_formed_unknown_ancillary_chunk(tmp_path):
    data = PNG_BYTES[:33] + png_chunk(b"tEXt", b"k\x00v") + PNG_BYTES[33:]
    worker, registry, _, _, transport_port, root = make_worker(tmp_path)
    artifact = write_png(root, data)
    payload = transcript(artifact)
    find_message(payload, "item/completed")["params"]["item"]["result"] = (
        base64.b64encode(data).decode()
    )
    sync_completed_turn_item(payload)
    transport_port.dispatch_results.append(payload)

    result = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert result["state"] == "ARTIFACT_READY"


@pytest.mark.parametrize("kind", ["file_size", "encoded_size"])
def test_artifact_and_base64_limits_are_checked_before_unbounded_work(
    tmp_path, monkeypatch, kind
):
    assert MAX_ARTIFACT_BYTES == 25 * 1024 * 1024
    assert MAX_BASE64_CHARS >= MAX_ARTIFACT_BYTES
    worker, registry, _, _, transport_port, root = make_worker(tmp_path)
    artifact = write_png(root)
    payload = transcript(artifact)
    if kind == "file_size":
        monkeypatch.setattr(worker_module, "MAX_ARTIFACT_BYTES", len(PNG_BYTES) - 1)
    else:
        monkeypatch.setattr(worker_module, "MAX_BASE64_CHARS", 8)
    transport_port.dispatch_results.append(payload)

    result = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert result["state"] == "UNKNOWN_OUTCOME"
    assert result["safe_reason_code"] == {
        "file_size": "artifact_format_invalid",
        "encoded_size": "image_item_terminal_semantics_unknown",
    }[kind]
    assert result["artifact"] is None


@pytest.mark.parametrize(
    ("change", "expected_reason"),
    [
        ({"transport": "websocket"}, "transport_not_admitted"),
        ({"protocol_version": "codex-app-server/next"}, "protocol_pin_mismatch"),
        ({"data_as_of": NOW + timedelta(seconds=1)}, "request_invalid"),
    ],
)
def test_request_transport_pin_and_data_time_are_fail_closed(
    tmp_path, change, expected_reason
):
    worker, registry, _, port, transport_port, _ = make_worker(tmp_path)

    result = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(**change),
    ).as_dict()

    assert result["state"] == "BLOCKED"
    assert result["safe_reason_code"] == expected_reason
    assert port.claim_calls == 0
    assert transport_port.dispatch_calls == transport_port.readback_calls == 0


@pytest.mark.parametrize(
    ("connector_ref", "tenant_ref"),
    [
        (None, "tenant-a"),
        ("", "tenant-a"),
        ("x" * 161, "tenant-a"),
        ("mcn_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", ""),
        ("mcn_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "t" * 161),
    ],
)
def test_invalid_connector_or_principal_tenant_returns_safe_blocked_observation(
    tmp_path, connector_ref, tenant_ref
):
    worker, _, _, port, transport_port, _ = make_worker(tmp_path)
    actor = Principal(
        actor_id="operator-invalid",
        roles=frozenset({"operator"}),
        tenant_ref=tenant_ref,
    )

    result = worker.run(
        principal=actor,
        connector_ref=connector_ref,
        request=request(),
    ).as_dict()

    assert (result["state"], result["safe_reason_code"]) == (
        "BLOCKED",
        "request_invalid",
    )
    assert port.peek_calls == port.claim_calls == 0
    assert transport_port.dispatch_calls == transport_port.readback_calls == 0
    assert "tenant" not in json.dumps(result).lower()


@pytest.mark.parametrize("drift", ["tenant", "provider", "capability", "revoked"])
def test_current_connector_binding_and_rotation_are_checked_before_claim(
    tmp_path, drift
):
    registry = FakeConnectorRegistry()
    actor = principal()
    if drift == "tenant":
        actor = principal("tenant-other")
    elif drift == "provider":
        registry.descriptor["provider"] = "comfyui"
    elif drift == "capability":
        registry.descriptor["capabilities"] = ["image_editing"]
    else:
        registry.descriptor["health"] = "REVOKED"
        registry.descriptor["revoked_at"] = NOW.isoformat()
    worker, _, _, port, transport_port, _ = make_worker(
        tmp_path, registry=registry
    )

    result = worker.run(
        principal=actor,
        connector_ref="mcn_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        request=request(),
    ).as_dict()

    assert result["state"] == "BLOCKED"
    assert result["safe_reason_code"] == "connector_not_currently_eligible"
    assert port.claim_calls == 0
    assert transport_port.dispatch_calls == transport_port.readback_calls == 0
    assert result["cross_scope_leakage_count"] == 0


@pytest.mark.parametrize(
    ("info", "state", "reason"),
    [
        ("unauthorized", "LOGIN_REQUIRED", "login_required"),
        ("usageLimitExceeded", "LIMITED", "usage_limited"),
        (
            {"responseStreamConnectionFailed": {"httpStatusCode": 429}},
            "LIMITED",
            "usage_limited",
        ),
    ],
)
def test_login_and_rate_limit_errors_map_only_to_safe_states(
    tmp_path, info, state, reason
):
    worker, registry, _, _, transport_port, _ = make_worker(tmp_path)
    transport_port.dispatch_results.append(paused_transcript(info))

    result = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert (result["state"], result["safe_reason_code"]) == (state, reason)
    serialized = json.dumps(result)
    assert "canary" not in serialized
    assert "provider-id" not in serialized.lower()


@pytest.mark.parametrize("paused_state", ["LOGIN_REQUIRED", "LIMITED"])
def test_pause_readback_then_explicit_resume_is_reachable_with_same_key(
    tmp_path, paused_state
):
    registry = FakeConnectorRegistry()
    store = DurableStore()
    info = "unauthorized" if paused_state == "LOGIN_REQUIRED" else "usageLimitExceeded"
    readback_method = (
        "account/updated"
        if paused_state == "LOGIN_REQUIRED"
        else "account/rateLimits/updated"
    )
    readback_params = (
        {"authMode": "chatgpt", "planType": "plus"}
        if paused_state == "LOGIN_REQUIRED"
        else {"limited": False, "observedAtMs": COMPLETED_AT_MS}
    )
    transport_port = FakeTransport(
        dispatch=[paused_transcript(info)],
        readback=[
            handshake_only(
                {
                    "direction": "server_notification",
                    "method": readback_method,
                    "params": readback_params,
                }
            )
        ],
    )
    worker, _, _, _, _, root = make_worker(
        tmp_path,
        registry=registry,
        store=store,
        transport=transport_port,
    )
    artifact = write_png(root)
    transport_port.dispatch_results.append(transcript(artifact))

    first = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()
    second = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()
    third = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(explicit_resume=True),
    ).as_dict()

    assert first["state"] == paused_state
    assert second["state"] == paused_state
    assert second["safe_reason_code"] == "fresh_readback_requires_explicit_resume"
    assert third["state"] == "ARTIFACT_READY"
    assert transport_port.dispatch_calls == 2
    assert transport_port.readback_calls == 1
    assert first["request_fingerprint_sha256"] == second[
        "request_fingerprint_sha256"
    ] == third["request_fingerprint_sha256"]
    assert (first["protocol_dispatch_attempt_count"], first["protocol_readback_attempt_count"]) == (
        1,
        0,
    )
    assert (second["protocol_dispatch_attempt_count"], second["protocol_readback_attempt_count"]) == (
        0,
        1,
    )
    assert (third["protocol_dispatch_attempt_count"], third["protocol_readback_attempt_count"]) == (
        1,
        0,
    )


@pytest.mark.parametrize(
    ("paused_state", "readback_method", "readback_params", "reason"),
    [
        (
            "LOGIN_REQUIRED",
            "account/updated",
            {"authMode": "none", "planType": None},
            "login_required",
        ),
        (
            "LIMITED",
            "account/rateLimits/updated",
            {"limited": True, "observedAtMs": COMPLETED_AT_MS},
            "usage_limited",
        ),
    ],
)
def test_fresh_readback_that_remains_paused_preserves_paused_state(
    tmp_path, paused_state, readback_method, readback_params, reason
):
    info = "unauthorized" if paused_state == "LOGIN_REQUIRED" else "usageLimitExceeded"
    still_paused = handshake_only(
        {
            "direction": "server_notification",
            "method": readback_method,
            "params": readback_params,
        }
    )
    transport_port = FakeTransport(
        dispatch=[paused_transcript(info)],
        readback=[deepcopy(still_paused), deepcopy(still_paused)],
    )
    worker, registry, _, port, _, _ = make_worker(tmp_path, transport=transport_port)

    first = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()
    second = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()
    third = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(explicit_resume=True),
    ).as_dict()

    assert first["state"] == paused_state
    for observation in (second, third):
        assert (observation["state"], observation["safe_reason_code"]) == (
            paused_state,
            reason,
        )
        assert observation["protocol_dispatch_attempt_count"] == 0
        assert observation["protocol_readback_attempt_count"] == 1
    assert port.reserve_count == 1
    assert transport_port.dispatch_calls == 1
    assert transport_port.readback_calls == 2


@pytest.mark.parametrize(
    "observed_at",
    [True, COMPLETED_AT_MS - 1_001, COMPLETED_AT_MS + 1_001],
)
def test_rate_limit_readback_timestamp_cannot_unlock_resume(tmp_path, observed_at):
    still_limited = handshake_only(
        {
            "direction": "server_notification",
            "method": "account/rateLimits/updated",
            "params": {"limited": False, "observedAtMs": observed_at},
        }
    )
    transport_port = FakeTransport(
        dispatch=[paused_transcript("usageLimitExceeded")],
        readback=[deepcopy(still_limited), deepcopy(still_limited)],
    )
    worker, registry, _, port, _, _ = make_worker(tmp_path, transport=transport_port)
    worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    )

    readback = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()
    resume = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(explicit_resume=True),
    ).as_dict()

    for observation in (readback, resume):
        assert (observation["state"], observation["safe_reason_code"]) == (
            "LIMITED",
            "usage_limited",
        )
    assert port.reserve_count == 1
    assert transport_port.dispatch_calls == 1
    assert transport_port.readback_calls == 2


@pytest.mark.parametrize(
    "observed_at",
    [COMPLETED_AT_MS - 1_000, COMPLETED_AT_MS + 1_000],
)
def test_rate_limit_readback_claim_window_boundaries_can_unlock_resume(
    tmp_path, observed_at
):
    registry = FakeConnectorRegistry()
    store = DurableStore()
    ready = handshake_only(
        {
            "direction": "server_notification",
            "method": "account/rateLimits/updated",
            "params": {"limited": False, "observedAtMs": observed_at},
        }
    )
    transport_port = FakeTransport(
        dispatch=[paused_transcript("usageLimitExceeded")],
        readback=[ready],
    )
    worker, _, _, _, _, root = make_worker(
        tmp_path,
        registry=registry,
        store=store,
        transport=transport_port,
    )
    transport_port.dispatch_results.append(transcript(write_png(root)))
    worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    )
    readback = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()
    resumed = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(explicit_resume=True),
    ).as_dict()

    assert readback["safe_reason_code"] == "fresh_readback_requires_explicit_resume"
    assert resumed["state"] == "ARTIFACT_READY"
    assert transport_port.dispatch_calls == 2
    assert transport_port.readback_calls == 1


def test_unknown_outcome_restart_uses_new_worker_and_shared_durable_readback(tmp_path):
    registry = FakeConnectorRegistry()
    store = DurableStore()
    first_transport = FakeTransport(
        dispatch=[ProtocolTransportDisconnected(after_dispatch=True)]
    )
    first_worker, _, _, _, _, root = make_worker(
        tmp_path,
        registry=registry,
        store=store,
        transport=first_transport,
    )
    artifact = write_png(root)
    first = first_worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    second_transport = FakeTransport(readback=[transcript(artifact)])
    second_worker, _, _, _, _, _ = make_worker(
        tmp_path,
        registry=registry,
        store=store,
        transport=second_transport,
    )
    second = second_worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(explicit_resume=True),
    ).as_dict()

    assert first["state"] == "UNKNOWN_OUTCOME"
    assert first["safe_reason_code"] == "transport_disconnected_after_dispatch"
    assert second["state"] == "ARTIFACT_READY"
    assert first_transport.dispatch_calls == 1
    assert second_transport.dispatch_calls == 0
    assert second_transport.readback_calls == 1
    assert second["protocol_dispatch_attempt_count"] == 0
    assert second["protocol_readback_attempt_count"] == 1
    assert first["request_fingerprint_sha256"] == second[
        "request_fingerprint_sha256"
    ]


def test_hard_crash_after_claim_before_record_restarts_as_readback_only(tmp_path):
    registry = FakeConnectorRegistry()
    store = DurableStore()
    crashing_transport = FakeTransport(dispatch=[SystemExit("hard-stop-canary")])
    first_worker, _, _, first_port, _, root = make_worker(
        tmp_path,
        registry=registry,
        store=store,
        transport=crashing_transport,
    )
    with pytest.raises(SystemExit, match="hard-stop-canary"):
        first_worker.run(
            principal=principal(),
            connector_ref=registry.descriptor["connector_ref"],
            request=request(),
        )
    assert first_port.reserve_count == 1
    assert first_port.record_calls == 0
    assert crashing_transport.dispatch_calls == 1
    assert next(iter(store.rows.values()))["state"] == "UNKNOWN_OUTCOME"

    artifact = write_png(root)
    recovery_transport = FakeTransport(readback=[transcript(artifact)])
    recovery_worker, _, _, recovery_port, _, _ = make_worker(
        tmp_path,
        registry=registry,
        store=store,
        transport=recovery_transport,
        clock=lambda: NOW + timedelta(minutes=2),
    )
    recovered = recovery_worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert recovered["state"] == "ARTIFACT_READY"
    assert recovery_port.reserve_count == 0
    assert recovery_transport.dispatch_calls == 0
    assert recovery_transport.readback_calls == 1


@pytest.mark.parametrize(
    "adapter_error",
    [
        RuntimeError("provider-body secret-canary"),
        PermissionError("provider-id secret-canary"),
        OSError("transport-path secret-canary"),
    ],
)
def test_transport_adapter_exceptions_are_sanitized_and_restart_readback_only(
    tmp_path, adapter_error
):
    registry = FakeConnectorRegistry()
    store = DurableStore()
    first_transport = FakeTransport(dispatch=[adapter_error])
    first_worker, _, _, first_port, _, root = make_worker(
        tmp_path,
        registry=registry,
        store=store,
        transport=first_transport,
    )
    first = first_worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    artifact = write_png(root)
    second_transport = FakeTransport(readback=[transcript(artifact)])
    second_worker, _, _, second_port, _, _ = make_worker(
        tmp_path,
        registry=registry,
        store=store,
        transport=second_transport,
    )
    replay = second_worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert (first["state"], first["safe_reason_code"]) == (
        "UNKNOWN_OUTCOME",
        "transport_adapter_failure",
    )
    assert "secret-canary" not in json.dumps(first, sort_keys=True)
    assert replay["state"] == "ARTIFACT_READY"
    assert first_transport.dispatch_calls == 1
    assert second_transport.dispatch_calls == 0
    assert second_transport.readback_calls == 1
    assert first_port.reserve_count == 1
    assert second_port.reserve_count == 0


def test_readback_and_record_adapter_failures_never_redispatch_or_leak(tmp_path):
    registry = FakeConnectorRegistry()
    store = DurableStore()
    first_transport = FakeTransport(
        dispatch=[ProtocolTransportDisconnected(after_dispatch=True)]
    )
    first_worker, _, _, _, _, root = make_worker(
        tmp_path, registry=registry, store=store, transport=first_transport
    )
    first_worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    )

    readback_transport = FakeTransport(
        readback=[RuntimeError("readback-provider secret-canary")]
    )
    readback_worker, _, _, readback_port, _, _ = make_worker(
        tmp_path, registry=registry, store=store, transport=readback_transport
    )
    readback_port.record_error = OSError("ledger-detail secret-canary")
    failed = readback_worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()
    assert (failed["state"], failed["safe_reason_code"]) == (
        "UNKNOWN_OUTCOME",
        "durable_record_failed",
    )
    assert "secret-canary" not in json.dumps(failed, sort_keys=True)
    assert readback_transport.dispatch_calls == 0
    assert readback_transport.readback_calls == 1

    artifact = write_png(root)
    final_transport = FakeTransport(readback=[transcript(artifact)])
    final_worker, _, _, _, _, _ = make_worker(
        tmp_path, registry=registry, store=store, transport=final_transport
    )
    recovered = final_worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()
    assert recovered["state"] == "ARTIFACT_READY"
    assert final_transport.dispatch_calls == 0
    assert final_transport.readback_calls == 1


@pytest.mark.parametrize("record_result", [None, "evd_" + "c" * 32])
def test_artifact_success_requires_durable_terminal_readback_and_evidence(
    tmp_path, record_result
):
    registry = FakeConnectorRegistry()
    store = DurableStore()
    worker, _, _, port, transport_port, root = make_worker(
        tmp_path, registry=registry, store=store
    )
    transport_port.dispatch_results.append(transcript(write_png(root)))
    port.record = lambda **_values: record_result

    result = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert (result["state"], result["safe_reason_code"]) == (
        "UNKNOWN_OUTCOME",
        "durable_record_failed",
    )
    assert result["artifact"] is None
    assert transport_port.dispatch_calls == 1
    assert next(iter(store.rows.values()))["state"] == "UNKNOWN_OUTCOME"

    recovery_transport = FakeTransport(readback=[transcript(write_png(root, name="recovered.png"))])
    recovery_worker, _, _, _, _, _ = make_worker(
        tmp_path,
        registry=registry,
        store=store,
        transport=recovery_transport,
    )
    recovered = recovery_worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()
    assert recovered["state"] == "ARTIFACT_READY"
    assert recovery_transport.dispatch_calls == 0
    assert recovery_transport.readback_calls == 1


@pytest.mark.parametrize(
    "drift",
    ["state", "binding", "authority", "evidence", "transition"],
)
def test_recorded_terminal_scope_hash_state_and_evidence_are_reverified(
    tmp_path, drift
):
    worker, registry, store, port, transport_port, root = make_worker(tmp_path)
    transport_port.dispatch_results.append(transcript(write_png(root)))
    original_record = port.record

    def tampering_record(**values):
        evidence_ref = original_record(**values)
        row = next(iter(store.rows.values()))
        if drift == "state":
            row["state"] = "FAILED"
        elif drift == "binding":
            row["binding"] = "f" * 64
        elif drift == "authority":
            row["authority"] = "f" * 64
        elif drift == "evidence":
            row["terminal_claim"] = replace(
                row["terminal_claim"], sealed_evidence_ref="evd_" + "f" * 32
            )
        else:
            row["terminal_claim"] = replace(
                row["terminal_claim"],
                sealed_transition=replace(
                    row["terminal_claim"].sealed_transition,
                    event_chain_sha256="f" * 64,
                ),
            )
        row["generation"] += 1
        return evidence_ref

    port.record = tampering_record
    result = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert (result["state"], result["safe_reason_code"]) == (
        "UNKNOWN_OUTCOME",
        "durable_record_failed",
    )
    assert result["artifact"] is None
    assert transport_port.dispatch_calls == 1


def test_immutable_request_drift_conflicts_before_provider(tmp_path):
    registry = FakeConnectorRegistry()
    store = DurableStore()
    transport_port = FakeTransport(
        dispatch=[ProtocolTransportDisconnected(after_dispatch=True)]
    )
    worker, _, _, _, _, _ = make_worker(
        tmp_path, registry=registry, store=store, transport=transport_port
    )
    worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    )

    drift = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(request_sha256="d" * 64),
    ).as_dict()

    assert drift["state"] == "BLOCKED"
    assert drift["safe_reason_code"] == "durable_claim_invalid"
    assert transport_port.dispatch_calls == 1
    assert transport_port.readback_calls == 0


def test_secret_canary_is_absent_from_every_observation_field(tmp_path):
    canary = "cookie=secret-canary bearer hidden-provider-id"
    worker, registry, _, _, transport_port, root = make_worker(tmp_path)
    artifact = write_png(root)
    transport_port.dispatch_results.append(transcript(artifact, revised_prompt=canary))

    result = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    serialized = json.dumps(result, sort_keys=True)
    assert "secret-canary" not in serialized
    assert "bearer hidden" not in serialized.lower()
    assert_zero_authority(result)


def test_terminal_transition_hash_scope_or_artifact_drift_is_rejected(tmp_path):
    worker, registry, store, _, transport_port, root = make_worker(tmp_path)
    artifact = write_png(root)
    transport_port.dispatch_results.append(transcript(artifact))
    worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    )
    row = next(iter(store.rows.values()))
    invalid_transition = replace(
        row["transition"], safe_reason_code="image_generation_failed"
    )
    terminal = replace(
        row["terminal_claim"],
        sealed_transition=invalid_transition,
        sealed_transition_sha256=None,
    )
    invalid_seal = sealed_transition_sha256(
        invalid_transition,
        claim=terminal,
        evidence_ref=row["evidence_ref"],
    )
    row["terminal_claim"] = replace(
        terminal, sealed_transition_sha256=invalid_seal
    )
    store.terminal_seals.add(invalid_seal)

    replay = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    # Even an authority-resealed transition cannot violate the terminal matrix.
    assert replay["state"] == "BLOCKED"
    assert replay["safe_reason_code"] == "durable_claim_invalid"
    assert transport_port.dispatch_calls == 1
    assert transport_port.readback_calls == 0


@pytest.mark.parametrize("actual_kind", ["websocket", "thread_shell", "unknown"])
def test_server_owned_transport_descriptor_cannot_be_disguised_by_request(
    tmp_path, actual_kind
):
    transport_port = FakeTransport(actual_transport_kind=actual_kind)
    worker, registry, _, port, _, _ = make_worker(tmp_path, transport=transport_port)

    result = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(transport="stdio"),
    ).as_dict()

    assert (result["state"], result["safe_reason_code"]) == (
        "BLOCKED",
        "transport_not_admitted",
    )
    assert port.peek_calls == port.claim_calls == port.record_calls == 0
    assert transport_port.dispatch_calls == transport_port.readback_calls == 0


@pytest.mark.parametrize("actual_kind", ["stdio", "unix"])
def test_server_owned_admitted_transport_kind_is_bound_to_runtime_receipt(
    tmp_path, actual_kind
):
    transport_port = FakeTransport(actual_transport_kind=actual_kind)
    worker, registry, _, _, _, root = make_worker(tmp_path, transport=transport_port)
    transport_port.dispatch_results.append(transcript(write_png(root)))

    result = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(transport=actual_kind),
    ).as_dict()

    assert result["state"] == "ARTIFACT_READY"


@pytest.mark.parametrize("field", ["actual_transport_kind", "adapter_version", "adapter_sha256"])
def test_transport_descriptor_drift_after_worker_initialization_blocks_before_peek(
    tmp_path, field
):
    transport_port = FakeTransport()
    worker, registry, _, port, _, _ = make_worker(tmp_path, transport=transport_port)
    replacement = {
        "actual_transport_kind": "websocket",
        "adapter_version": "drifted-adapter-v2",
        "adapter_sha256": "f" * 64,
    }[field]
    setattr(transport_port, field, replacement)

    result = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert (result["state"], result["safe_reason_code"]) == (
        "BLOCKED",
        "transport_not_admitted",
    )
    assert port.peek_calls == port.claim_calls == port.record_calls == 0
    assert transport_port.dispatch_calls == transport_port.readback_calls == 0


def _paused_dangling_readback(kind: str, paused_state: str) -> dict[str, Any]:
    success_events = deepcopy(FIXTURE["success_transcript"][3:])
    ready = {
        "direction": "server_notification",
        "method": (
            "account/updated"
            if paused_state == "LOGIN_REQUIRED"
            else "account/rateLimits/updated"
        ),
        "params": (
            {"authMode": "chatgpt", "planType": "plus"}
            if paused_state == "LOGIN_REQUIRED"
            else {"limited": False, "observedAtMs": COMPLETED_AT_MS}
        ),
    }
    if kind == "turn_then_ready":
        events = [success_events[0], ready]
    elif kind == "ready_then_turn":
        events = [ready, success_events[0]]
    else:
        events = success_events[:2]
    return {
        "messages": [*deepcopy(FIXTURE["success_transcript"][:3]), *events],
        "disconnected": False,
    }


@pytest.mark.parametrize("paused_state", ["LOGIN_REQUIRED", "LIMITED"])
@pytest.mark.parametrize(
    "kind", ["turn_then_ready", "ready_then_turn", "dangling_item"]
)
def test_paused_readback_with_any_unfinished_media_event_never_unlocks_dispatch(
    tmp_path, paused_state, kind
):
    info = (
        "unauthorized" if paused_state == "LOGIN_REQUIRED" else "usageLimitExceeded"
    )
    malformed = _paused_dangling_readback(kind, paused_state)
    transport_port = FakeTransport(
        dispatch=[paused_transcript(info)],
        readback=[deepcopy(malformed), deepcopy(malformed)],
    )
    worker, registry, _, port, _, _ = make_worker(tmp_path, transport=transport_port)

    paused = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()
    readback = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()
    retry = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(explicit_resume=True),
    ).as_dict()

    assert paused["state"] == paused_state
    assert readback["state"] == retry["state"] == "UNKNOWN_OUTCOME"
    assert readback["safe_reason_code"] == retry["safe_reason_code"] == (
        "protocol_event_out_of_order"
    )
    assert port.reserve_count == 1
    assert transport_port.dispatch_calls == 1
    assert transport_port.readback_calls == 2


@pytest.mark.parametrize(
    ("info", "expected_state", "expected_reason"),
    [
        ("unauthorized", "LOGIN_REQUIRED", "login_required"),
        ("usageLimitExceeded", "LIMITED", "usage_limited"),
    ],
)
def test_auth_and_limit_turn_errors_take_priority_over_failed_image_item(
    tmp_path, info, expected_state, expected_reason
):
    worker, registry, _, _, transport_port, root = make_worker(tmp_path)
    payload = transcript(write_png(root))
    item = find_message(payload, "item/completed")["params"]["item"]
    item.pop("savedPath")
    item.update(result="", status="failed", revisedPrompt="bounded-redacted")
    turn = find_message(payload, "turn/completed")["params"]["turn"]
    turn.update(
        status="failed",
        error={
            "message": "provider-body-canary",
            "additionalDetails": None,
            "codexErrorInfo": info,
        },
    )
    sync_completed_turn_item(payload)
    transport_port.dispatch_results.append(payload)

    result = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert (result["state"], result["safe_reason_code"]) == (
        expected_state,
        expected_reason,
    )
    assert "provider-body-canary" not in json.dumps(result, sort_keys=True)


def test_unknown_turn_status_with_valid_error_is_not_a_known_pause(tmp_path):
    worker, registry, _, _, transport_port, root = make_worker(tmp_path)
    payload = transcript(write_png(root))
    turn = find_message(payload, "turn/completed")["params"]["turn"]
    turn.update(
        status="futureStatus",
        error={
            "message": "provider-body-canary",
            "additionalDetails": None,
            "codexErrorInfo": "unauthorized",
        },
    )
    transport_port.dispatch_results.append(payload)

    result = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert (result["state"], result["safe_reason_code"]) == (
        "UNKNOWN_OUTCOME",
        "protocol_event_malformed",
    )


@pytest.mark.parametrize(
    ("started_at_ms", "completed_at_ms", "expected_state"),
    [
        (COMPLETED_AT_MS, COMPLETED_AT_MS - 1, "UNKNOWN_OUTCOME"),
        (COMPLETED_AT_MS - 1_000, COMPLETED_AT_MS + 1_000, "UNKNOWN_OUTCOME"),
        (COMPLETED_AT_MS - 1_000, COMPLETED_AT_MS + 999, "ARTIFACT_READY"),
    ],
)
def test_item_timestamps_are_monotonic_and_bound_to_quantized_turn_window(
    tmp_path, started_at_ms, completed_at_ms, expected_state
):
    worker, registry, _, _, transport_port, root = make_worker(tmp_path)
    payload = transcript(write_png(root))
    find_message(payload, "item/started")["params"]["startedAtMs"] = started_at_ms
    find_message(payload, "item/completed")["params"][
        "completedAtMs"
    ] = completed_at_ms
    transport_port.dispatch_results.append(payload)

    result = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert result["state"] == expected_state
    if expected_state == "UNKNOWN_OUTCOME":
        assert result["safe_reason_code"] == "protocol_completion_time_invalid"


@pytest.mark.parametrize(
    "budget_kind",
    ["messages", "field", "metadata", "depth", "container", "result"],
)
def test_protocol_budget_rejects_before_event_hash_or_artifact_io(
    tmp_path, monkeypatch, budget_kind
):
    worker, registry, _, _, transport_port, root = make_worker(tmp_path)
    payload = transcript(write_png(root))
    if budget_kind == "messages":
        payload["messages"] = [
            {"x": index} for index in range(MAX_PROTOCOL_MESSAGES + 1)
        ]
    elif budget_kind == "field":
        payload["messages"] = [{"x": "a" * (MAX_PROTOCOL_FIELD_CHARS + 1)}]
    elif budget_kind == "metadata":
        payload["messages"] = [
            {"x": "a" * MAX_PROTOCOL_FIELD_CHARS}
            for _ in range(MAX_PROTOCOL_METADATA_CHARS // MAX_PROTOCOL_FIELD_CHARS + 1)
        ]
    elif budget_kind == "depth":
        nested: dict[str, Any] = {"leaf": 1}
        for _ in range(MAX_PROTOCOL_DEPTH + 1):
            nested = {"nested": nested}
        payload["messages"] = [nested]
    elif budget_kind == "container":
        payload["messages"] = [{"x": [0] * (MAX_PROTOCOL_CONTAINER_ITEMS + 1)}]
    else:
        monkeypatch.setattr(worker_module, "MAX_BASE64_CHARS", 8)
        find_message(payload, "item/completed")["params"]["item"]["result"] = (
            "A" * 9
        )
        sync_completed_turn_item(payload)
    monkeypatch.setattr(
        worker_module,
        "_bounded_event_chain_sha256",
        lambda _messages: pytest.fail("event hash ran before protocol budget"),
    )
    monkeypatch.setattr(
        CodexAppServerImageWorker,
        "_artifact_receipt",
        lambda *_args, **_kwargs: pytest.fail(
            "artifact I/O ran before protocol budget"
        ),
    )
    transport_port.dispatch_results.append(payload)

    result = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert result["state"] == "UNKNOWN_OUTCOME"
    assert result["artifact"] is None


@pytest.mark.parametrize(
    ("location", "field"),
    [
        ("client", "providerRequestId"),
        ("result", "providerRequestId"),
        ("server", "providerRequestId"),
    ],
)
def test_handshake_unknown_fields_are_rejected_without_provider_canary_projection(
    tmp_path, location, field
):
    worker, registry, _, _, transport_port, root = make_worker(tmp_path)
    payload = transcript(write_png(root))
    initialize = payload["messages"][0]
    response = payload["messages"][1]
    target = {
        "client": initialize["params"]["clientInfo"],
        "result": response["result"],
        "server": response["result"]["serverInfo"],
    }[location]
    target[field] = "provider-secret-canary"
    transport_port.dispatch_results.append(payload)

    result = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert result["state"] == "UNKNOWN_OUTCOME"
    assert result["safe_reason_code"] in {
        "protocol_handshake_invalid",
        "protocol_pin_mismatch",
    }
    assert "provider-secret-canary" not in json.dumps(result, sort_keys=True)


@pytest.mark.parametrize("numeric", [float("nan"), float("inf"), 2**63])
def test_protocol_budget_rejects_nonfinite_or_unbounded_numeric_leaves(
    tmp_path, numeric
):
    worker, registry, _, _, transport_port, _ = make_worker(tmp_path)
    payload = {
        "messages": [{"numeric": numeric}],
        "disconnected": False,
    }
    transport_port.dispatch_results.append(payload)

    result = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert (result["state"], result["safe_reason_code"]) == (
        "UNKNOWN_OUTCOME",
        "protocol_event_malformed",
    )


@pytest.mark.parametrize(
    ("method", "params"),
    [
        ("account/updated", {"authMode": "chatgpt", "planType": {"secret": 1}}),
        ("account/updated", {"authMode": "futureAuth", "planType": None}),
        (
            "account/rateLimits/updated",
            {"limited": "false", "observedAtMs": COMPLETED_AT_MS},
        ),
    ],
)
def test_pause_readback_fields_require_exact_admitted_types(tmp_path, method, params):
    paused_state = "LOGIN_REQUIRED" if method == "account/updated" else "LIMITED"
    info = "unauthorized" if paused_state == "LOGIN_REQUIRED" else "usageLimitExceeded"
    malformed = handshake_only(
        {
            "direction": "server_notification",
            "method": method,
            "params": params,
        }
    )
    transport_port = FakeTransport(
        dispatch=[paused_transcript(info)],
        readback=[malformed],
    )
    worker, registry, _, _, _, _ = make_worker(tmp_path, transport=transport_port)
    worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    )

    result = worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert (result["state"], result["safe_reason_code"]) == (
        "UNKNOWN_OUTCOME",
        "protocol_event_malformed",
    )
    assert "secret" not in json.dumps(result, sort_keys=True)


@pytest.mark.parametrize("drift", ["tenant", "connector", "fingerprint"])
def test_cross_scope_terminal_peek_is_blocked_without_artifact_or_evidence_leak(
    tmp_path, drift
):
    registry = FakeConnectorRegistry()
    store = DurableStore()
    first_worker, _, _, _, first_transport, root = make_worker(
        tmp_path, registry=registry, store=store
    )
    first_transport.dispatch_results.append(transcript(write_png(root)))
    first_worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    )

    second_worker, _, _, port, second_transport, _ = make_worker(
        tmp_path, registry=registry, store=store
    )
    original_peek = port.peek

    def drifted_peek(**values):
        peek = original_peek(**values)
        changes = {
            "tenant": {"tenant_ref": "tenant-other"},
            "connector": {"connector_ref": "mcn_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},
            "fingerprint": {"request_fingerprint_sha256": "f" * 64},
        }[drift]
        return replace(peek, **changes)

    port.peek = drifted_peek
    blocked = second_worker.run(
        principal=principal(),
        connector_ref=registry.descriptor["connector_ref"],
        request=request(),
    ).as_dict()

    assert (blocked["state"], blocked["safe_reason_code"]) == (
        "BLOCKED",
        "durable_claim_invalid",
    )
    assert blocked["artifact"] is None
    assert blocked["dispatch_ref"] is None
    assert "evd_" not in json.dumps(blocked, sort_keys=True)
    assert port.claim_calls == port.record_calls == 0
    assert second_transport.dispatch_calls == second_transport.readback_calls == 0

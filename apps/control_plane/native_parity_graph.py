from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .agent_harness import (
    GoalTaskRow,
    GraphNodeRow,
    GraphNodeStatusBindingRow,
    GraphProjectRow,
    HarnessObservationRow,
    VerifierRegistryRow,
)
from .native_parity_acceptance import (
    ACCEPTANCE_DIMENSIONS,
    NativeParityAcceptanceWorkspace,
    RegistryMappingAcceptanceRecords,
)

_ARTIFACT_DIMENSIONS = frozenset(ACCEPTANCE_DIMENSIONS) - {
    "external_graph_verifier"
}
_HEX = frozenset("0123456789abcdef")
_SCOPE_FIELDS = (
    "tenant_ref",
    "entity_ref",
    "store_ref",
    "provider_id",
    "capability_id",
    "capability_version",
)


class SqlNativeParityAcceptanceRecords:
    """Read complete native-parity bundles from the canonical Harness/Graph ledger.

    The adapter deliberately emits no partial observations.  A capability is visible
    as more than its registry mapping only when all eight dimension nodes, immutable
    status bindings, tasks, verifier contracts and latest observations form one
    exact-scope, exact-input bundle.  State reduction remains exclusively owned by
    :class:`NativeParityAcceptanceWorkspace`.
    """

    GRAPH_KIND = "native_parity_acceptance"
    ARTIFACT_NODE_TYPE = "native_parity_artifact_dimension"
    GRAPH_NODE_TYPE = "native_parity_external_graph_verifier"
    EXTERNAL_SOURCE_TYPE = "external_graph"
    EXTERNAL_AUTHORITY = "external_verifier"

    def __init__(
        self,
        *,
        engine: Any,
        mappings: RegistryMappingAcceptanceRecords,
    ) -> None:
        self._engine = engine
        self._mappings = mappings

    def read_records(
        self,
        *,
        tenant_ref: str,
        entity_ref: str,
        store_ref: str,
        as_of: datetime,
    ) -> list[dict[str, Any]]:
        cutoff = self._utc(as_of)
        mapping_records = self._mappings.read_records(
            tenant_ref=tenant_ref,
            entity_ref=entity_ref,
            store_ref=store_ref,
            as_of=cutoff,
        )
        output = list(mapping_records)
        with Session(self._engine) as session:
            for mapping in mapping_records:
                scope = {
                    "tenant_ref": tenant_ref,
                    "entity_ref": entity_ref,
                    "store_ref": store_ref,
                    "provider_id": mapping["provider_id"],
                    "capability_id": mapping["capability_id"],
                    "capability_version": mapping["capability_version"],
                }
                bundle = self._read_bundle(session, scope=scope, cutoff=cutoff)
                if bundle is not None:
                    output.extend(bundle)
        return output

    def _read_bundle(
        self,
        session: Session,
        *,
        scope: dict[str, str],
        cutoff: datetime,
    ) -> list[dict[str, Any]] | None:
        projects = list(
            session.scalars(
                select(GraphProjectRow).where(
                    GraphProjectRow.tenant_ref == scope["tenant_ref"],
                    GraphProjectRow.entity_ref == scope["entity_ref"],
                    GraphProjectRow.store_ref == scope["store_ref"],
                    GraphProjectRow.created_at <= cutoff,
                )
            )
        )
        complete: list[list[dict[str, Any]]] = []
        for project in projects:
            candidate = self._project_bundle(
                session, project=project, scope=scope, cutoff=cutoff
            )
            if candidate is not None:
                complete.append(candidate)
        if len(complete) == 1:
            return complete[0]
        if len(complete) > 1:
            return [self._integrity_failure(scope, "competing_complete_projects")]
        return None

    def _project_bundle(
        self,
        session: Session,
        *,
        project: GraphProjectRow,
        scope: dict[str, str],
        cutoff: datetime,
    ) -> list[dict[str, Any]] | None:
        if (
            project.lifecycle != "active"
            or not self._digest(project.baseline_sha256)
            or not self._digest(project.goal_contract_sha256)
        ):
            return None
        nodes = list(
            session.scalars(
                select(GraphNodeRow).where(
                    GraphNodeRow.project_id == project.id,
                    GraphNodeRow.graph_kind == self.GRAPH_KIND,
                    GraphNodeRow.created_at <= cutoff,
                )
            )
        )
        by_dimension: dict[str, GraphNodeRow] = {}
        for node in nodes:
            node_scope = node.scope_json if isinstance(node.scope_json, dict) else {}
            if any(node_scope.get(field) != expected for field, expected in scope.items()):
                continue
            dimension = node_scope.get("dimension")
            if dimension not in ACCEPTANCE_DIMENSIONS:
                return [self._integrity_failure(scope, "unknown_dimension_node")]
            if dimension in by_dimension:
                return [self._integrity_failure(scope, "duplicate_dimension_node")]
            expected_type = (
                self.GRAPH_NODE_TYPE
                if dimension == "external_graph_verifier"
                else self.ARTIFACT_NODE_TYPE
            )
            if (
                node.node_type != expected_type
                or node.authority != "canonical"
                or node.version != scope["capability_version"]
                or not node.source.strip()
                or not self._digest(node.content_sha256)
                or not self._digest(node_scope.get("acceptance_input_sha256"))
                or not self._digest(node_scope.get("evidence_sha256"))
                or not str(node_scope.get("producer_id") or "").strip()
            ):
                return [self._integrity_failure(scope, "dimension_node_contract_invalid")]
            by_dimension[dimension] = node
        if set(by_dimension) != set(ACCEPTANCE_DIMENSIONS):
            return None
        input_hashes = {
            node.scope_json["acceptance_input_sha256"] for node in by_dimension.values()
        }
        if len(input_hashes) != 1:
            return [self._integrity_failure(scope, "acceptance_input_hash_drift")]

        records: list[dict[str, Any]] = []
        for sequence, dimension in enumerate(ACCEPTANCE_DIMENSIONS, start=1):
            record = self._dimension_record(
                session,
                project=project,
                node=by_dimension[dimension],
                dimension=dimension,
                scope=scope,
                cutoff=cutoff,
                sequence=sequence,
            )
            if record is None:
                return None
            records.append(record)
        return records

    def _dimension_record(
        self,
        session: Session,
        *,
        project: GraphProjectRow,
        node: GraphNodeRow,
        dimension: str,
        scope: dict[str, str],
        cutoff: datetime,
        sequence: int,
    ) -> dict[str, Any] | None:
        bindings = list(
            session.scalars(
                select(GraphNodeStatusBindingRow).where(
                    GraphNodeStatusBindingRow.project_id == project.id,
                    GraphNodeStatusBindingRow.node_id == node.id,
                    GraphNodeStatusBindingRow.binding_role == "status_source",
                    GraphNodeStatusBindingRow.created_at <= cutoff,
                )
            )
        )
        if not bindings:
            return None
        if len(bindings) > 1:
            return self._integrity_failure(scope, "ambiguous_status_binding")
        binding = bindings[0]
        expected_binding_hash = self._hash(
            {
                "project_id": project.id,
                "node_id": node.id,
                "task_id": binding.task_id,
                "binding_role": "status_source",
            }
        )
        if not hmac.compare_digest(binding.content_sha256, expected_binding_hash):
            return self._integrity_failure(scope, "status_binding_hash_invalid")
        task = session.get(GoalTaskRow, binding.task_id)
        if (
            task is None
            or task.project_id != project.id
            or self._utc(task.created_at) > cutoff
            or not self._digest(task.fingerprint)
        ):
            return self._integrity_failure(scope, "status_task_contract_invalid")
        verifier = session.get(
            VerifierRegistryRow,
            {"id": task.verifier_id, "version": task.verifier_version},
        )
        if verifier is None or not self._valid_verifier(verifier, cutoff=cutoff):
            return self._integrity_failure(scope, "verifier_contract_invalid")
        observations = list(
            session.scalars(
                select(HarnessObservationRow)
                .where(
                    HarnessObservationRow.project_id == project.id,
                    HarnessObservationRow.task_id == task.id,
                    HarnessObservationRow.observed_at <= cutoff,
                )
                .order_by(
                    HarnessObservationRow.observed_at.desc(),
                    HarnessObservationRow.id.desc(),
                )
            )
        )
        if not observations:
            return None
        observation = observations[0]
        node_scope = node.scope_json
        observation_scope = (
            observation.scope_json if isinstance(observation.scope_json, dict) else {}
        )
        required_observation_scope = {
            **scope,
            "dimension": dimension,
            "acceptance_input_sha256": node_scope["acceptance_input_sha256"],
            "subject_sha256": node.content_sha256,
            "evidence_sha256": node_scope["evidence_sha256"],
            "producer_id": node_scope["producer_id"],
        }
        if any(
            observation_scope.get(field) != expected
            for field, expected in required_observation_scope.items()
        ):
            return self._integrity_failure(scope, "latest_observation_scope_mismatch")
        expected_kind = (
            "external_graph" if dimension == "external_graph_verifier" else "external_harness"
        )
        if observation_scope.get("verifier_kind") != expected_kind:
            return self._integrity_failure(scope, "latest_observation_verifier_kind_invalid")
        if (
            observation.verifier_id != verifier.id
            or observation.verifier_version != verifier.version
            or observation.authority != verifier.authority
            or observation.source != node.source
            or observation.input_sha256 != node_scope["acceptance_input_sha256"]
            or observation.state not in {"passed", "failed"}
            or self._utc(observation.recorded_at) < self._utc(observation.observed_at)
            or observation.recorded_by != verifier.id
            or observation.recorded_by == node_scope["producer_id"]
        ):
            return self._integrity_failure(scope, "latest_observation_authority_invalid")
        expected_result = self._hash(
            {
                "state": observation.state,
                "summary": observation.summary,
                "artifact_ref": observation.artifact_ref,
                "evidence_ref": observation.evidence_ref,
            }
        )
        if not hmac.compare_digest(observation.result_sha256, expected_result):
            return self._integrity_failure(scope, "latest_observation_hash_invalid")
        observed_at = self._utc(observation.observed_at)
        expires_at = self._utc(observation.fresh_until)
        if expires_at != observed_at + timedelta(seconds=verifier.freshness_seconds):
            return self._integrity_failure(scope, "latest_observation_freshness_invalid")
        record = {
            **scope,
            "record_kind": "observation",
            "record_id": observation.id,
            "sequence": sequence,
            "recorded_at": observed_at,
            "dimension": dimension,
            "status": observation.state,
            "expires_at": expires_at,
            "producer_id": node_scope["producer_id"],
            "verifier_id": verifier.id,
            "verifier_kind": expected_kind,
            "acceptance_input_sha256": observation.input_sha256,
            "subject_sha256": node.content_sha256,
            "evidence_sha256": node_scope["evidence_sha256"],
        }
        record["record_sha256"] = NativeParityAcceptanceWorkspace._hash(record)
        return record

    @staticmethod
    def _integrity_failure(scope: dict[str, str], reason: str) -> dict[str, Any]:
        """Emit an intentionally invalid row so the workspace reports blocked.

        Absence remains gated, while a present but corrupt latest authority is
        visible as an integrity failure and can never fall back to mapping-only.
        """
        return {
            **scope,
            "record_id": f"integrity-failure:{reason}",
            "record_kind": "integrity_failure",
            "integrity_failure_reason": reason,
        }

    def _valid_verifier(self, verifier: VerifierRegistryRow, *, cutoff: datetime) -> bool:
        contract = {
            "id": verifier.id,
            "version": verifier.version,
            "source_type": verifier.source_type,
            "authority": verifier.authority,
            "success_states": verifier.success_states_json,
            "freshness_seconds": verifier.freshness_seconds,
        }
        return bool(
            verifier.enabled
            and self._utc(verifier.created_at) <= cutoff
            and verifier.source_type == self.EXTERNAL_SOURCE_TYPE
            and verifier.authority == self.EXTERNAL_AUTHORITY
            and verifier.success_states_json == ["passed"]
            and verifier.freshness_seconds > 0
            and self._digest(verifier.contract_sha256)
            and hmac.compare_digest(verifier.contract_sha256, self._hash(contract))
        )

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def _digest(value: Any) -> bool:
        return isinstance(value, str) and len(value) == 64 and not set(value) - _HEX

    @staticmethod
    def _hash(value: Any) -> str:
        payload = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=lambda item: SqlNativeParityAcceptanceRecords._utc(item).isoformat()
            if isinstance(item, datetime)
            else str(item),
        )
        return hashlib.sha256(payload.encode()).hexdigest()

"""Durable observation-only delivery for TeamAgent terminal outcomes."""

from __future__ import annotations

from typing import Any

from .agent_team_orchestration import TeamAgentHarnessBridge
from .enterprise_control import ExactScope
from .outbox import OutboxService
from .team_agent_postgres_runtime import PostgresTeamAgentRuntime


class TeamAgentTerminalOutboxPublisher:
    """Replay terminal publication intents through the existing Harness bridge.

    The outbox owns retry/claim state. The bridge and sink remain the owners of
    exact-scope authorization and durable observation idempotency.
    """

    def __init__(
        self,
        *,
        runtime: PostgresTeamAgentRuntime,
        outbox: OutboxService,
        bridge: TeamAgentHarnessBridge,
        project_id: str,
        principal: Any,
        verifier_id: str,
        verifier_version: str,
    ) -> None:
        self.runtime = runtime
        self.outbox = outbox
        self.bridge = bridge
        self.project_id = project_id
        self.principal = principal
        self.verifier_id = verifier_id
        self.verifier_version = verifier_version

    def publish_batch(
        self,
        *,
        worker_id: str,
        limit: int = 50,
        lease_seconds: int = 60,
    ) -> dict[str, Any]:
        def deliver(event: dict[str, Any]) -> None:
            payload = event.get("payload")
            if not isinstance(payload, dict):
                raise ValueError("terminal outbox payload must be an object")
            if payload.get("contract_id") != "team-agent-terminal-observation-outbox@1":
                raise ValueError("unsupported terminal outbox contract")
            scope = ExactScope(
                str(payload["tenant_ref"]),
                str(payload["entity_ref"]),
                str(payload["store_ref"]),
            )
            session_ref = str(payload["session_ref"])
            self.bridge.publish_completed(
                session_ref=session_ref,
                project_id=self.project_id,
                verifier_id=self.verifier_id,
                verifier_version=self.verifier_version,
                principal=self.principal,
                scope=scope,
                authority_sha256=str(payload["authority_sha256"]),
            )

        return self.outbox.publish_batch(
            worker_id=worker_id,
            limit=limit,
            lease_seconds=lease_seconds,
            deliver=deliver,
        )


__all__ = ["TeamAgentTerminalOutboxPublisher"]

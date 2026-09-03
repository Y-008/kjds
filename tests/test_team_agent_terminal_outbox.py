from types import SimpleNamespace

import pytest

from apps.control_plane.team_agent_terminal_outbox import (
    TeamAgentTerminalOutboxPublisher,
)


class _Outbox:
    def __init__(self, event):
        self.event = event

    def publish_batch(self, *, deliver, **kwargs):
        deliver(self.event)
        return {"claimed": 1, "published": [self.event["event_id"]], "failed": []}


class _Bridge:
    def __init__(self):
        self.calls = []

    def publish_completed(self, **kwargs):
        self.calls.append(kwargs)
        return ()


def _publisher(event):
    bridge = _Bridge()
    publisher = TeamAgentTerminalOutboxPublisher(
        runtime=SimpleNamespace(),
        outbox=_Outbox(event),
        bridge=bridge,
        project_id="project-a",
        principal=SimpleNamespace(actor_id="monitor-a"),
        verifier_id="team-agent-terminal-observation",
        verifier_version="1",
    )
    return publisher, bridge


def test_terminal_outbox_replays_exact_scope_without_result_payload():
    event = {
        "event_id": "evt-terminal-1",
        "payload": {
            "contract_id": "team-agent-terminal-observation-outbox@1",
            "session_ref": "session-a",
            "task_ref": "task-a",
            "state": "passed",
            "tenant_ref": "tenant-a",
            "entity_ref": "entity-a",
            "store_ref": "store-a",
            "authority_sha256": "a" * 64,
        },
    }
    publisher, bridge = _publisher(event)

    result = publisher.publish_batch(worker_id="publisher-a")

    assert result["published"] == ["evt-terminal-1"]
    call = bridge.calls[0]
    assert call["session_ref"] == "session-a"
    assert call["scope"].tenant_ref == "tenant-a"
    assert call["authority_sha256"] == "a" * 64
    assert "result" not in event["payload"]


def test_terminal_outbox_rejects_unknown_contract_before_sink():
    publisher, bridge = _publisher(
        {
            "event_id": "evt-terminal-2",
            "payload": {"contract_id": "wrong@1"},
        }
    )

    with pytest.raises(ValueError, match="unsupported terminal outbox contract"):
        publisher.publish_batch(worker_id="publisher-a")
    assert bridge.calls == []

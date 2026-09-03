from argparse import Namespace
from datetime import UTC, datetime
from types import SimpleNamespace

import scripts.compile_teamagent_control_snapshot as control_snapshot

CAPTURED_AT = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)


class FrozenDateTime:
    @classmethod
    def now(cls, tz=None):
        assert tz is UTC
        return CAPTURED_AT


def test_snapshot_has_fixed_priority_queue_and_stable_canonical_hash(
    monkeypatch,
) -> None:
    monkeypatch.setattr(control_snapshot, "datetime", FrozenDateTime)
    monkeypatch.setattr(
        control_snapshot,
        "GlobalPortfolioOrchestrator",
        lambda: SimpleNamespace(snapshot=lambda: {}),
    )
    monkeypatch.setattr(control_snapshot, "LoopEngineeringService", object)
    monkeypatch.setattr(
        control_snapshot,
        "_summary_portfolio",
        lambda _snapshot: {"fixture": "portfolio"},
    )
    monkeypatch.setattr(
        control_snapshot,
        "_summary_loop",
        lambda _service: {"fixture": "loop"},
    )
    monkeypatch.setattr(
        control_snapshot,
        "_maybe_harness_snapshot",
        lambda _args: {
            "status": "unavailable",
            "external_write_allowed": False,
        },
    )
    args = Namespace(harness_project_id=None)

    first = control_snapshot.build_snapshot(args)
    second = control_snapshot.build_snapshot(args)

    assert [
        (item["rank"], item["work_item"])
        for item in first["execution_queue"]
    ] == [
        (1, "BAS-223 / current-head G1"),
        (2, "D10 供应、checkout、CM3 证据"),
        (3, "AI 编排内核 shadow hardening"),
    ]
    assert all(
        item["control_boundary"]["external_write_allowed"] is False
        for item in first["execution_queue"]
    )
    assert first == second

    payload = control_snapshot._stable_snapshot_projection(first)
    reordered_payload = dict(reversed(list(payload.items())))
    assert first["captured_at"] == CAPTURED_AT.isoformat()
    assert first["snapshot_sha256"] == control_snapshot._sha(payload)
    assert control_snapshot._canonical(payload) == control_snapshot._canonical(
        reordered_payload
    )
    assert control_snapshot._sha(payload) == control_snapshot._sha(
        reordered_payload
    )


def test_snapshot_hash_excludes_capture_time_but_keeps_it_for_audit(
    monkeypatch,
) -> None:
    class AdvancingDateTime:
        values = iter(
            (
                CAPTURED_AT,
                CAPTURED_AT.replace(minute=1),
            )
        )

        @classmethod
        def now(cls, tz=None):
            assert tz is UTC
            return next(cls.values)

    monkeypatch.setattr(control_snapshot, "datetime", AdvancingDateTime)
    monkeypatch.setattr(
        control_snapshot,
        "GlobalPortfolioOrchestrator",
        lambda: SimpleNamespace(snapshot=lambda: {}),
    )
    monkeypatch.setattr(control_snapshot, "LoopEngineeringService", object)
    monkeypatch.setattr(
        control_snapshot,
        "_summary_portfolio",
        lambda _snapshot: {"fixture": "portfolio"},
    )
    monkeypatch.setattr(
        control_snapshot,
        "_summary_loop",
        lambda _service: {"fixture": "loop"},
    )
    monkeypatch.setattr(
        control_snapshot,
        "_maybe_harness_snapshot",
        lambda _args: {
            "status": "unavailable",
            "external_write_allowed": False,
        },
    )
    args = Namespace(harness_project_id=None)

    first = control_snapshot.build_snapshot(args)
    second = control_snapshot.build_snapshot(args)

    assert first["captured_at"] != second["captured_at"]
    assert first["snapshot_sha256"] == second["snapshot_sha256"]
    assert control_snapshot._stable_snapshot_projection(
        first
    ) == control_snapshot._stable_snapshot_projection(second)

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apps.control_plane.agent_harness import AgentHarnessService
from apps.control_plane.database import create_database_engine
from apps.control_plane.global_expert_team import GlobalPortfolioOrchestrator
from apps.control_plane.loop_engineering import LoopEngineeringService
from apps.control_plane.security import Principal

CONTRACT_ID = "kjds-teamagent-control-snapshot-v1"


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _stable_snapshot_projection(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the semantic projection protected by ``snapshot_sha256``.

    ``captured_at`` is observation metadata, not control state. Including it
    would give identical portfolio/loop/Harness projections a different hash
    on every read and make replay, comparison, and deduplication impossible.
    """

    return {
        key: value
        for key, value in payload.items()
        if key not in {"captured_at", "snapshot_sha256"}
    }


def _summary_portfolio(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_id": snapshot["contract_id"],
        "registry_sha256": snapshot["registry_sha256"],
        "leader_role": snapshot["leader"]["role_id"],
        "portfolio_scope": snapshot["selection"]["portfolio_scope"],
        "selection": snapshot["selection"],
        "operating_status": snapshot["operating_status"],
        "control_boundary": snapshot["control_boundary"],
        "counts": snapshot["counts"],
    }


def _summary_loop(service: LoopEngineeringService) -> dict[str, Any]:
    registry = service.registry_snapshot()
    evolution = service.evolution_snapshot()
    modules = {
        module["id"]: {
            "state": module["state"],
            "promotion_gate": module["promotion_gate"],
            "required_controls": list(module["required_controls"]),
        }
        for module in registry["modules"]
    }
    return {
        "registry_id": registry["registry_id"],
        "version": registry["version"],
        "registry_sha256": service.registry_sha256,
        "modules": modules,
        "loop_contract": list(registry["loop_contract"]),
        "team_agent_contract": registry["team_agent_contract"],
        "evolution_contract_id": evolution["contract_id"],
        "evolution_states": list(evolution["states"]),
        "allowed_transitions": list(evolution["allowed_transitions"]),
        "transition_controls": evolution["transition_controls"],
    }


def _maybe_harness_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    if not args.harness_project_id:
        return {
            "status": "unavailable",
            "reason": "harness_project_id not supplied",
            "external_write_allowed": False,
        }

    engine = create_database_engine()
    service = AgentHarnessService(engine)
    principal = Principal(
        actor_id=args.actor_id,
        roles=frozenset({"monitor"}),
        tenant_ref=args.tenant_ref,
        store_refs=frozenset({args.store_ref}),
    )
    as_of = (
        datetime.fromisoformat(args.as_of)
        if args.as_of
        else datetime.now(UTC)
    )
    workspace = service.workspace(
        args.harness_project_id,
        principal=principal,
        store_ref=args.store_ref,
        as_of=as_of,
    )
    return {
        "status": workspace["status"],
        "contract_id": workspace["contract_id"],
        "project_id": args.harness_project_id,
        "store_ref": args.store_ref,
        "scope": workspace["scope"],
        "counts": workspace["counts"],
        "task_states": {
            task["id"]: task["state"] for task in workspace.get("tasks", [])
        },
        "snapshot_sha256": workspace["snapshot_sha256"],
        "authority": workspace.get("authority"),
        "external_write_allowed": False,
        "workspace": workspace,
    }


def build_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    portfolio = GlobalPortfolioOrchestrator()
    loop = LoopEngineeringService()
    portfolio_snapshot = portfolio.snapshot()
    loop_snapshot = _summary_loop(loop)
    harness_snapshot = _maybe_harness_snapshot(args)
    queue = [
        {
            "rank": 1,
            "work_item": "BAS-223 / current-head G1",
            "why": "Keep the main engineering gate and release baseline moving first.",
            "source": "project_control_commercialization",
            "control_boundary": {"external_write_allowed": False},
        },
        {
            "rank": 2,
            "work_item": "D10 供应、checkout、CM3 证据",
            "why": "Continue the actual-cash and operational evidence path without confusing it with control-plane work.",
            "source": "sku_closed_loop",
            "control_boundary": {"external_write_allowed": False},
        },
        {
            "rank": 3,
            "work_item": "AI 编排内核 shadow hardening",
            "why": "Harden the TeamAgent / subagent control kernel while keeping it in-process and read-only.",
            "source": "global_expert_orchestration",
            "control_boundary": {"external_write_allowed": False},
        },
    ]
    payload = {
        "contract_id": CONTRACT_ID,
        "captured_at": datetime.now(UTC).isoformat(),
        "control_boundary": {
            "external_write_allowed": False,
            "runtime_dependency_allowed": False,
            "formal_fact_promotion_allowed": False,
        },
        "global_portfolio": _summary_portfolio(portfolio_snapshot),
        "loop_engineering": loop_snapshot,
        "harness_snapshot": harness_snapshot,
        "execution_queue": queue,
    }
    payload["snapshot_sha256"] = _sha(_stable_snapshot_projection(payload))
    return payload


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compile a read-only TeamAgent control snapshot."
    )
    parser.add_argument("--output", type=Path, help="Optional output path for the JSON snapshot.")
    parser.add_argument("--harness-project-id", help="Optional live Harness project id to snapshot.")
    parser.add_argument("--tenant-ref", default="default", help="Tenant ref used for an optional live Harness snapshot.")
    parser.add_argument("--store-ref", default="ozon-primary", help="Store ref used for an optional live Harness snapshot.")
    parser.add_argument("--actor-id", default="control-snapshot-monitor", help="Principal actor id used for an optional live Harness snapshot.")
    parser.add_argument("--as-of", help="Optional ISO-8601 timestamp for the live Harness snapshot.")
    parser.add_argument("--compact", action="store_true", help="Emit compact JSON instead of pretty JSON.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    payload = build_snapshot(args)
    text = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if args.compact
        else json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    ) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.global_expert_team import GlobalPortfolioOrchestrator
from apps.control_plane.operating_intelligence import OperatingIntelligenceService
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base
from apps.control_plane.team_control_tower import (
    TeamControlTower,
    TeamControlTowerError,
)

REGISTRY_PATH = (
    Path(__file__).parents[1]
    / "docs"
    / "project"
    / "registries"
    / "team_control_tower_registry.json"
)
WORKSTREAM_PATH = (
    Path(__file__).parents[1]
    / "docs"
    / "project"
    / "registries"
    / "active_workstream_assignments.json"
)


class FakeLedger:
    pass


class FakeEvidence:
    def __init__(self) -> None:
        self.validated: list[list[str]] = []

    def require_valid(self, evidence_ids) -> None:
        self.validated.append(list(evidence_ids))


class FakeScopedEvidence:
    def __init__(self) -> None:
        self.projected: list[list[str]] = []

    def project(self, *, evidence_ids, **_) -> dict:
        self.projected.append(list(evidence_ids))
        return {"status": "ready"}


class FakeBenchmark:
    def __init__(self, *, groups: list[dict] | None = None, no_data: bool = False) -> None:
        self.groups = groups or []
        self.no_data = no_data
        self.reads = 0
        self.request_sha256 = "b" * 64

    def list(self, **kwargs) -> dict:
        self.reads += 1
        assert kwargs["expected_scope_authority_sha256"] == "a" * 64
        return {
            "contract_id": "kjds-strategic-benchmark-kernel-v1",
            "items": [] if self.no_data else [self._snapshot()],
            "next_cursor": None,
        }

    def get(self, **kwargs) -> dict:
        self.reads += 1
        assert kwargs["expected_scope_authority_sha256"] == "a" * 64
        return {
            "contract_id": "kjds-strategic-benchmark-kernel-v1",
            "snapshot": self._snapshot(),
            "groups": self.groups,
        }

    def _snapshot(self) -> dict:
        return {
            "snapshot_ref": "benchmark-snapshot-1",
            "store_ref": "ozon-primary",
            "registry_schema": "kjds-strategic-benchmark-contracts-v1",
            "registry_sha256": "c" * 64,
            "as_of": "2026-08-06T07:00:00+00:00",
            "created_at": "2026-08-06T07:01:00+00:00",
            "request_sha256": self.request_sha256,
            "global_top1_claim": False,
        }


class DriftingBenchmark(FakeBenchmark):
    def list(self, **kwargs) -> dict:
        self.reads += 1
        raise RuntimeError("authority drift")


class FakeSettlementCash:
    def __init__(self, *, verified: bool = False) -> None:
        self.verified = verified
        self.reads = 0

    def project(self, **kwargs) -> dict:
        self.reads += 1
        assert kwargs["entity_scope"]["authority_sha256"] == "a" * 64
        cycles = []
        if self.verified:
            cycles = [
                {
                    "reconciliation_key": "private-order-ref",
                    "stage": "reconciled",
                    "books": {
                        "order_accrual": {"order_fact_count": 1},
                        "platform_settlement": {"status": "observed"},
                        "bank_cash": {"status": "observed"},
                    },
                    "actual_cash_cm3": {
                        "status": "available",
                        "amount": "321.00",
                    },
                    "evidence": {"all_current_and_exact_scope": True},
                    "blockers": [],
                }
            ]
        count = 1 if self.verified else 0
        core = {
            "contract_id": "kjds-native-exact-scope-settlement-cash-control-v1",
            "status": "ready" if self.verified else "no_data",
            "as_of": kwargs["as_of"],
            "scope": {
                "tenant_ref": kwargs["principal"].tenant_ref,
                "entity_ref": kwargs["entity_scope"]["entity_ref"],
                "store_ref": kwargs["store_ref"],
                "scope_grant_authority_sha256": kwargs["entity_scope"][
                    "authority_sha256"
                ],
            },
            "counts": {
                "total_cycles": count,
                "order_fact_cycles": count,
                "settlement_cycles": count,
                "cash_cycles": count,
                "reconciled": count,
                "actual_cash_cm3_available": count,
            },
            "cycles": cycles,
            "excluded": {"count": 0},
            "control_envelope": {
                "read_only": True,
                "scoped_input_read": True,
                "external_write_allowed": False,
                "finance_entry_created": False,
                "reconciliation_created": False,
                "fact_created": False,
                "approval_created": False,
                "permit_created": False,
                "payment_initiated": False,
            },
        }
        core["snapshot_sha256"] = hashlib.sha256(
            json.dumps(
                core,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        return core


def benchmark_group(
    *,
    peer_count: int = 5,
    leader: bool = True,
    state: str = "comparable",
    group_ref: str = "group-customer-outcome",
) -> dict:
    current = {
        "observation_ref": "kjds-current-1",
        "subject_class": "kjds_current",
        "value_projection": {"mode": "public_exact", "value": "0.91"},
        "freshness_due_at": "2026-09-01T00:00:00+00:00",
        "eligibility_state": "stale" if state == "stale" else "eligible",
    }
    peers = [
        {
            "observation_ref": f"peer-{index}",
            "subject_class": "peer",
            "value_projection": {"mode": "public_exact", "value": "0.80"},
            "freshness_due_at": "2026-09-01T00:00:00+00:00",
            "eligibility_state": "eligible",
        }
        for index in range(peer_count)
    ]
    return {
        "group_ref": group_ref,
        "domain": "product_experience",
        "metric_id": "core_task_success",
        "comparison_state": state,
        "leader_observation_refs": ["kjds-current-1" if leader else "peer-0"],
        "cohort_ref": "ru-ozon-peer-cohort",
        "market": "RU",
        "window": {
            "start": "2026-07-01T00:00:00+00:00",
            "end": "2026-08-01T00:00:00+00:00",
        },
        "result_sha256": "d" * 64,
        "observations": [current, *peers],
        "global_top1_claim": False,
    }


def build_service(
    *,
    strategic_benchmark=None,
    settlement_cash=None,
    clock=None,
) -> tuple[TeamControlTower, OperatingIntelligenceService]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    evidence = FakeEvidence()
    scoped = FakeScopedEvidence()
    tasks = OperatingIntelligenceService(
        engine=engine,
        profit_ledger=FakeLedger(),
        evidence=evidence,
        scoped_evidence=scoped,
    )
    control_now = datetime.now(UTC) + timedelta(days=1)
    return (
        TeamControlTower(
            expert_team=GlobalPortfolioOrchestrator(),
            operating_tasks=tasks,
            scoped_evidence=scoped,
            strategic_benchmark=strategic_benchmark,
            settlement_cash=settlement_cash,
            clock=clock or (lambda: control_now),
        ),
        tasks,
    )


def scope() -> dict:
    return {
        "principal": Principal(
            actor_id="operator-1",
            roles=frozenset({"operator"}),
            tenant_ref="tenant-cn-1",
            store_refs=frozenset({"ozon-primary"}),
        ),
        "entity_scope": {
            "status": "ready",
            "entity_ref": "entity-cn-1",
            "authority_sha256": "a" * 64,
        },
        "store_ref": "ozon-primary",
    }


def finish_campaign_phase_one(tower: TeamControlTower) -> None:
    brief = tower.brief(**scope())
    assert brief["next_action"]["target"]["type"] == "campaign_phase"
    tower.advance(
        **scope(),
        continuation=brief["next_action"]["continuation"],
        result="take",
        rationale="打开组织和战役冻结阶段",
        evidence_ids=(),
        idempotency_key="campaign-open",
    )
    brief = tower.brief(**scope())
    tower.advance(
        **scope(),
        continuation=brief["next_action"]["continuation"],
        result="take",
        rationale="Program Director 领取阶段",
        evidence_ids=(),
        idempotency_key="campaign-ack",
    )
    brief = tower.brief(**scope())
    tower.advance(
        **scope(),
        continuation=brief["next_action"]["continuation"],
        result="take",
        rationale="以当前 exact-scope Evidence 正式 kickoff",
        evidence_ids=("evd-campaign-kickoff",),
        idempotency_key="campaign-start",
    )
    brief = tower.brief(**scope())
    tower.advance(
        **scope(),
        continuation=brief["next_action"]["continuation"],
        result="done",
        rationale="阶段工作交接完成，等待正式 Gate",
        evidence_ids=("evd-campaign-phase-one",),
        idempotency_key="campaign-resolve",
    )


def test_brief_projects_the_four_image_flows_and_exactly_one_next_action():
    tower, _ = build_service()

    result = tower.brief(**scope())

    assert [item["flow_ref"] for item in result["flows"]] == [
        "project_control_commercialization",
        "sku_closed_loop",
        "dual_engine_commercialization",
        "lg001_exact_scope",
    ]
    assert result["next_action"]["target"] == {
        "type": "campaign_phase",
        "campaign_ref": "ru-ozon-top1-90d",
        "phase_ref": "day_1_7_organization_freeze",
        "expected_status": "BLOCKED",
    }
    assert result["next_action"]["allowed_results"] == ["take"]
    assert len(result["next_action"]["continuation"]) == 64
    assert result["executive_summary"]["flow_count"] == 4
    assert result["team"] == {
        "leader": "global_chief_commerce_officer",
        "specialist_count": 12,
        "control_role_count": 5,
        "escalation_chain": [
            "accountable_specialist",
            "country_or_domain_lead",
            "global_chief_commerce_officer",
            "independent_professional_authority",
            "human_business_owner_and_independent_approver",
        ],
    }
    assert result["control_envelope"]["projection_only"] is True
    assert all(
        value is False
        for key, value in result["control_envelope"].items()
        if key != "projection_only"
    )


def test_brief_projects_top1_organization_cash_campaign_and_five_gates_without_claims():
    tower, _ = build_service()

    result = tower.brief(**scope())

    assert result["organization_readiness"]["status"] == "UNKNOWN"
    assert result["organization_readiness"]["contract_counts"] == {
        "human_core_required": 18,
        "ai_specialists_required": 12,
        "expert_pool_target": {"minimum": 20, "maximum": 40},
        "independent_control_roles_required": 5,
    }
    assert result["organization_readiness"]["verified_bindings"]["human_core"] == 0
    assert result["critical_path"]["actual_campaign_day"] is None
    assert result["critical_path"]["planned_end_on"] == "2026-11-04"
    assert len(result["critical_path"]["phases"]) == 4
    assert result["top1_scorecard"]["global_top1_claim"] is False
    assert len(result["top1_scorecard"]["dimensions"]) == 12
    assert result["cash_at_risk"]["status"] == "UNKNOWN"
    assert result["cash_at_risk"]["forecast_invoked"] is False
    assert result["cash_at_risk"]["thirteen_week_cash"]["forecast"] is None
    assert result["cash_at_risk"]["actual_cash_truth"]["status"] == "UNKNOWN"
    assert result["delivery_gate"]["gate_count"] == 5
    assert result["delivery_gate"]["passed_gate_count"] == 0
    assert len(result["decision_basis_sha256"]) == 64
    assert result["next_action"]["decision_basis_sha256"] == result["decision_basis_sha256"]


def test_registry_has_exact_machine_verifiable_team_contract():
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    organization = payload["organization_model"]

    assert len(organization["core_roles"]) == 18
    assert len({item["role_id"] for item in organization["core_roles"]}) == 18
    assert organization["ai_specialists_required"] == 12
    assert len(organization["ai_specialist_role_refs"]) == 12
    assert len(set(organization["ai_specialist_role_refs"])) == 12
    assert organization["expert_pool_target"] == {"minimum": 20, "maximum": 40}
    assert len(organization["control_role_refs"]) == 5
    assert len(payload["top1_scorecard_profile"]["dimensions"]) == 12
    assert [(item["day_from"], item["day_to"]) for item in payload["campaign_90d"]["phases"]] == [
        (1, 7),
        (8, 30),
        (31, 60),
        (61, 90),
    ]


def test_scope_invalid_brief_reads_no_operating_tasks_and_exposes_no_continuation():
    benchmark = FakeBenchmark(groups=[benchmark_group()])
    settlement = FakeSettlementCash(verified=True)
    tower, tasks = build_service(
        strategic_benchmark=benchmark,
        settlement_cash=settlement,
    )
    values = scope()
    values["entity_scope"] = {"status": "no_data", "reason": "grant_missing"}

    result = tower.brief(**values)

    assert result["status"] == "scope_invalid"
    assert result["scope"] is None
    assert result["next_action"] is None
    assert all(item["runtime_status"] == "scope_invalid" for item in result["flows"])
    assert tasks.tasks() == []
    assert benchmark.reads == 0
    assert settlement.reads == 0
    assert result["decision_basis_sha256"] is None
    assert result["top1_scorecard"]["status"] == "UNKNOWN"


@pytest.mark.parametrize(
    ("groups", "expected_status", "leadership_status", "gap_status"),
    [
        ([benchmark_group()], "VERIFIED", "METRIC_LEADER", "CLOSED"),
        ([benchmark_group(leader=False)], "VERIFIED", "NOT_LEADER", "OPEN"),
        ([benchmark_group(peer_count=4)], "PARTIAL", "UNKNOWN", "UNKNOWN"),
        ([benchmark_group(state="stale")], "STALE", "UNKNOWN", "UNKNOWN"),
        (
            [benchmark_group(), benchmark_group(group_ref="duplicate-group")],
            "CONFLICTED",
            "UNKNOWN",
            "UNKNOWN",
        ),
    ],
)
def test_benchmark_selector_projects_existing_leader_refs_without_reranking(
    groups: list[dict],
    expected_status: str,
    leadership_status: str,
    gap_status: str,
):
    tower, _ = build_service(strategic_benchmark=FakeBenchmark(groups=groups))

    result = tower.brief(**scope())
    dimension = result["top1_scorecard"]["dimensions"][0]

    assert dimension["status"] == expected_status
    assert dimension["leadership_status"] == leadership_status
    assert dimension["gap_status"] == gap_status
    assert result["top1_scorecard"]["global_top1_claim"] is False


def test_benchmark_no_data_and_authority_drift_remain_explicit_unknown_or_conflicted():
    no_data, _ = build_service(strategic_benchmark=FakeBenchmark(no_data=True))
    drift, _ = build_service(strategic_benchmark=DriftingBenchmark())

    no_data_result = no_data.brief(**scope())
    drift_result = drift.brief(**scope())

    assert no_data_result["top1_scorecard"]["status"] == "UNKNOWN"
    assert "strategic_benchmark_no_data" in no_data_result["top1_scorecard"]["reason_codes"]
    assert drift_result["top1_scorecard"]["status"] == "CONFLICTED"
    assert "strategic_benchmark_authority_drift" in drift_result["top1_scorecard"]["reason_codes"]


def test_malformed_benchmark_projection_fails_closed():
    malformed = benchmark_group()
    malformed.pop("result_sha256")
    tower, _ = build_service(strategic_benchmark=FakeBenchmark(groups=[malformed]))

    with pytest.raises(TeamControlTowerError, match="group shape drift"):
        tower.brief(**scope())


def test_benchmark_projection_change_invalidates_old_continuation():
    benchmark = FakeBenchmark(groups=[benchmark_group(leader=False)])
    tower, _ = build_service(strategic_benchmark=benchmark)
    first = tower.brief(**scope())
    benchmark.groups = [benchmark_group(leader=True)]
    benchmark.request_sha256 = "e" * 64

    second = tower.brief(**scope())

    assert first["decision_basis_sha256"] != second["decision_basis_sha256"]
    assert first["next_action"]["continuation"] != second["next_action"]["continuation"]
    with pytest.raises(TeamControlTowerError, match="continuation is stale"):
        tower.advance(
            **scope(),
            continuation=first["next_action"]["continuation"],
            result="take",
            rationale="使用已失效的决策基线",
            evidence_ids=(),
            idempotency_key="stale-benchmark-basis",
        )


def test_campaign_kickoff_requires_evidence_and_never_auto_passes_gate():
    tower, _ = build_service()
    brief = tower.brief(**scope())
    tower.advance(
        **scope(),
        continuation=brief["next_action"]["continuation"],
        result="take",
        rationale="打开战役首阶段",
        evidence_ids=(),
        idempotency_key="kickoff-open",
    )
    brief = tower.brief(**scope())
    tower.advance(
        **scope(),
        continuation=brief["next_action"]["continuation"],
        result="take",
        rationale="领取战役首阶段",
        evidence_ids=(),
        idempotency_key="kickoff-ack",
    )
    start_brief = tower.brief(**scope())

    assert start_brief["next_action"]["evidence_required"] is True
    assert start_brief["critical_path"]["actual_campaign_day"] is None
    with pytest.raises(TeamControlTowerError, match="requires exact-scope Evidence"):
        tower.advance(
            **scope(),
            continuation=start_brief["next_action"]["continuation"],
            result="take",
            rationale="缺少 Evidence 的 kickoff",
            evidence_ids=(),
            idempotency_key="kickoff-start-missing",
        )
    tower.advance(
        **scope(),
        continuation=start_brief["next_action"]["continuation"],
        result="take",
        rationale="绑定 exact-scope Evidence 的 kickoff",
        evidence_ids=("evd-kickoff-current-scope",),
        idempotency_key="kickoff-start-ready",
    )

    kicked_off = tower.brief(**scope())
    assert kicked_off["critical_path"]["kickoff"]["status"] == "VERIFIED"
    assert kicked_off["critical_path"]["actual_campaign_day"] >= 1
    assert kicked_off["critical_path"]["phases"][0]["status"] == "PARTIAL"
    assert kicked_off["delivery_gate"]["passed_gate_count"] == 0
    assert all(
        gate["formal_gate_pass"] is False
        for gate in kicked_off["delivery_gate"]["gates"]
    )


def test_phase_completion_is_handoff_only_and_returns_focus_to_frozen_flows():
    tower, _ = build_service()

    finish_campaign_phase_one(tower)
    brief = tower.brief(**scope())

    assert brief["critical_path"]["phases"][0]["runtime_task_status"] == "resolved"
    assert brief["critical_path"]["phases"][0]["status"] == "PARTIAL"
    assert brief["critical_path"]["phases"][1]["current_operating_task"] is None
    assert brief["next_action"]["target"]["flow_ref"] == "lg001_exact_scope"
    assert brief["delivery_gate"]["passed_gate_count"] == 0


def test_exact_scope_reconciled_cash_cycle_is_projected_without_raw_values():
    settlement = FakeSettlementCash(verified=True)
    tower, _ = build_service(settlement_cash=settlement)

    result = tower.brief(**scope())
    truth = result["cash_at_risk"]["actual_cash_truth"]

    assert truth["status"] == "VERIFIED"
    assert truth["verified_cycle_count"] == 1
    assert "platform_settlement" not in result["cash_at_risk"]["missing_authorities"]
    assert "bank_cash" not in result["cash_at_risk"]["missing_authorities"]
    assert result["cash_at_risk"]["status"] == "UNKNOWN"
    assert result["cash_at_risk"]["forecast_invoked"] is False
    serialized = json.dumps(truth)
    assert "private-order-ref" not in serialized
    assert "321.00" not in serialized
    russia_gate = next(
        gate
        for gate in result["delivery_gate"]["gates"]
        if gate["gate_ref"] == "russia_operating_truth_gate"
    )
    assert russia_gate["readiness_status"] == "VERIFIED"
    assert russia_gate["formal_gate_pass"] is False


def test_cash_authority_change_invalidates_old_continuation():
    settlement = FakeSettlementCash()
    tower, _ = build_service(settlement_cash=settlement)
    first = tower.brief(**scope())
    settlement.verified = True

    second = tower.brief(**scope())

    assert first["decision_basis_sha256"] != second["decision_basis_sha256"]
    assert first["next_action"]["continuation"] != second["next_action"]["continuation"]
    with pytest.raises(TeamControlTowerError, match="continuation is stale"):
        tower.advance(
            **scope(),
            continuation=first["next_action"]["continuation"],
            result="take",
            rationale="使用现金权威变化前的 continuation",
            evidence_ids=(),
            idempotency_key="stale-cash-basis",
        )


def test_observation_time_change_keeps_decision_basis_and_continuation_stable():
    observed_at = [datetime.now(UTC) + timedelta(days=1)]
    tower, _ = build_service(
        settlement_cash=FakeSettlementCash(verified=True),
        clock=lambda: observed_at[0],
    )
    first = tower.brief(**scope())
    observed_at[0] += timedelta(seconds=5)

    second = tower.brief(**scope())

    assert first["snapshot_sha256"] != second["snapshot_sha256"]
    assert first["decision_basis_sha256"] == second["decision_basis_sha256"]
    assert first["next_action"]["continuation"] == second["next_action"]["continuation"]
    receipt = tower.advance(
        **scope(),
        continuation=first["next_action"]["continuation"],
        result="take",
        rationale="时间推进但业务权威未变化",
        evidence_ids=(),
        idempotency_key="stable-across-observation-time",
    )
    assert receipt["outcome"] == "accepted"


def test_settlement_cash_scope_drift_fails_closed():
    class WrongScopeSettlement(FakeSettlementCash):
        def project(self, **kwargs) -> dict:
            result = super().project(**kwargs)
            result.pop("snapshot_sha256")
            result["scope"]["entity_ref"] = "wrong-entity"
            result["snapshot_sha256"] = hashlib.sha256(
                json.dumps(
                    result,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            ).hexdigest()
            return result

    tower, _ = build_service(settlement_cash=WrongScopeSettlement(verified=True))

    with pytest.raises(TeamControlTowerError, match="exact scope drift"):
        tower.brief(**scope())


def test_advance_opens_existing_operating_task_then_progresses_idempotently():
    tower, tasks = build_service()
    finish_campaign_phase_one(tower)
    first_brief = tower.brief(**scope())
    assert first_brief["next_action"]["target"]["flow_ref"] == "lg001_exact_scope"

    opened = tower.advance(
        **scope(),
        continuation=first_brief["next_action"]["continuation"],
        result="take",
        rationale="开始总控工程交付",
        evidence_ids=(),
        idempotency_key="lg001-open-v1",
    )

    assert opened["outcome"] == "accepted"
    assert opened["operating_task"]["status"] == "open"
    task_id = opened["operating_task"]["id"]
    persisted = tasks.tasks()[0]
    assert persisted["id"] == task_id
    assert persisted["metric_id"].startswith("internal:team_control:")
    assert persisted["snapshot"]["control_tower"]["flow_ref"] == "lg001_exact_scope"
    assert persisted["snapshot"]["expert_route"]["accountable_specialist"] == (
        "architecture_engineering_security_release"
    )
    assert persisted["snapshot"]["external_write_allowed"] is False

    acknowledge_brief = tower.brief(**scope())
    command = {
        **scope(),
        "continuation": acknowledge_brief["next_action"]["continuation"],
        "result": "take",
        "rationale": "负责人确认领取",
        "evidence_ids": (),
        "idempotency_key": "lg001-ack-v1",
    }
    acknowledged = tower.advance(**command)
    replayed = tower.advance(**command)

    assert acknowledged["operating_task"]["status"] == "acknowledged"
    assert replayed["outcome"] == "idempotent_replay"
    assert replayed["operating_task"]["id"] == task_id
    assert [item["event_type"] for item in tasks.task_events(task_id)] == [
        "opened",
        "acknowledge",
    ]


def test_completion_requires_exact_scope_evidence_and_moves_focus_to_sku_loop():
    tower, _ = build_service()
    finish_campaign_phase_one(tower)
    brief = tower.brief(**scope())
    tower.advance(
        **scope(),
        continuation=brief["next_action"]["continuation"],
        result="take",
        rationale="打开 LG-001",
        evidence_ids=(),
        idempotency_key="open-lg001",
    )
    brief = tower.brief(**scope())
    tower.advance(
        **scope(),
        continuation=brief["next_action"]["continuation"],
        result="take",
        rationale="领取 LG-001",
        evidence_ids=(),
        idempotency_key="ack-lg001",
    )
    brief = tower.brief(**scope())
    tower.advance(
        **scope(),
        continuation=brief["next_action"]["continuation"],
        result="take",
        rationale="开始 LG-001",
        evidence_ids=(),
        idempotency_key="start-lg001",
    )
    brief = tower.brief(**scope())

    with pytest.raises(TeamControlTowerError, match="requires Evidence"):
        tower.advance(
            **scope(),
            continuation=brief["next_action"]["continuation"],
            result="done",
            rationale="完成 LG-001",
            evidence_ids=(),
            idempotency_key="resolve-lg001-missing-evidence",
        )
    resolved = tower.advance(
        **scope(),
        continuation=brief["next_action"]["continuation"],
        result="done",
        rationale="完成 LG-001 并绑定工程 Evidence",
        evidence_ids=("evd-lg001-engineering",),
        idempotency_key="resolve-lg001",
    )

    assert resolved["operating_task"]["status"] == "resolved"
    next_brief = tower.brief(**scope())
    assert next_brief["next_action"]["target"]["flow_ref"] == "sku_closed_loop"
    assert next_brief["flows"][3]["runtime_status"] == "resolved"


def test_stale_continuation_and_idempotency_drift_fail_closed():
    tower, _ = build_service()
    brief = tower.brief(**scope())
    command = {
        **scope(),
        "continuation": brief["next_action"]["continuation"],
        "result": "take",
        "rationale": "打开当前唯一动作",
        "evidence_ids": (),
        "idempotency_key": "same-key",
    }
    tower.advance(**command)

    with pytest.raises(TeamControlTowerError, match="payload drift"):
        tower.advance(**{**command, "rationale": "不同请求内容"})
    with pytest.raises(TeamControlTowerError, match="continuation is stale"):
        tower.advance(**{**command, "idempotency_key": "new-key"})


def test_registry_drift_fails_closed(tmp_path: Path):
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    payload["control_boundary"]["performs_external_write"] = True
    path = tmp_path / "team-control.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    tower, tasks = build_service()

    with pytest.raises(TeamControlTowerError, match="boundary"):
        TeamControlTower(
            expert_team=GlobalPortfolioOrchestrator(),
            operating_tasks=tasks,
            registry_path=path,
        )


def test_registry_flow_must_reference_a_current_authoritative_lane(tmp_path: Path):
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    payload["flows"][3]["source_lane_ids"] = ["C", "UNKNOWN-LANE"]
    path = tmp_path / "team-control.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    tower, tasks = build_service()

    with pytest.raises(TeamControlTowerError, match="unknown workstream lane"):
        TeamControlTower(
            expert_team=GlobalPortfolioOrchestrator(),
            operating_tasks=tasks,
            registry_path=path,
            workstream_path=WORKSTREAM_PATH,
        )


@pytest.mark.parametrize(
    ("drift", "match"),
    [
        ("core_count", "18 core role"),
        ("unknown_selector", "selector is unknown"),
        ("duplicate_phase", "phase identifiers"),
        ("verified_binding_without_evidence", "binding Evidence"),
        ("control_role_reference", "control role set"),
        ("campaign_authority", "coordination authority"),
        ("actual_cash_authority", "Actual cash authority"),
        ("delivery_gate_authority", "Delivery gate authority"),
    ],
)
def test_v12_registry_contract_drift_fails_closed(
    tmp_path: Path,
    drift: str,
    match: str,
):
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if drift == "core_count":
        payload["organization_model"]["core_roles"].pop()
    elif drift == "unknown_selector":
        payload["top1_scorecard_profile"]["dimensions"][0]["benchmark_selector"] = {
            "domain": "unknown",
            "metric_id": "unknown",
        }
    elif drift == "duplicate_phase":
        payload["campaign_90d"]["phases"][1]["phase_ref"] = payload[
            "campaign_90d"
        ]["phases"][0]["phase_ref"]
    elif drift == "verified_binding_without_evidence":
        binding = payload["organization_model"]["core_roles"][0]["binding"]
        binding.update(
            {
                "status": "verified_active",
                "primary_human_ref": "human-primary",
                "alternate_human_ref": "human-alternate",
                "conflict_attestation_evidence_ref": "evidence-conflict",
                "budget_cap_status": "VERIFIED",
                "maximum_loss_status": "VERIFIED",
            }
        )
    elif drift == "control_role_reference":
        payload["organization_model"]["control_role_refs"][0] = "unknown_control"
    elif drift == "campaign_authority":
        payload["campaign_90d"]["coordination"][
            "task_completion_proves_gate_pass"
        ] = True
    elif drift == "actual_cash_authority":
        payload["cash_at_risk_policy"]["actual_cash_authority"][
            "satisfies_thirteen_week_forecast"
        ] = True
    else:
        payload["delivery_gate_profile"]["task_or_calendar_can_pass"] = True
    path = tmp_path / f"team-control-{drift}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    _, tasks = build_service()

    with pytest.raises(TeamControlTowerError, match=match):
        TeamControlTower(
            expert_team=GlobalPortfolioOrchestrator(),
            operating_tasks=tasks,
            registry_path=path,
            workstream_path=WORKSTREAM_PATH,
        )

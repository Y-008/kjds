import hashlib
import hmac
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.causal_experiments import (
    CausalExperimentService,
    ExperimentProtocolRow,
)
from apps.control_plane.decision_contracts import DecisionContractService
from apps.control_plane.decision_lifecycle import DecisionLifecycleService
from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.sql_repository import Base


def setup_services():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    contracts = DecisionContractService(engine=engine, evidence=evidence)
    decisions = DecisionLifecycleService(
        engine=engine,
        contracts=contracts,
        evidence=evidence,
    )
    experiments = CausalExperimentService(
        engine=engine,
        decisions=decisions,
        evidence=evidence,
    )
    return engine, evidence, contracts, decisions, experiments


def capture(evidence: EvidenceService, ref: str):
    return evidence.capture(
        content=f"immutable evidence for {ref}".encode(),
        filename=f"{ref}.txt",
        content_type="text/plain",
        source="causal_experiment_test",
        source_ref=f"test://{ref}",
        grade=EvidenceGrade.A,
        effective_at="2026-07-17T00:00:00+00:00",
        effective_until=None,
        created_by="tester",
    )


def experiment_resolution(contracts, decisions, evidence_id):
    contract = contracts.create(
        profile="/x10think",
        objective="验证新版详情页是否提高每访客贡献利润",
        decision_domain="listing",
        risk_level="high",
        maximum_loss_amount=Decimal("1000"),
        currency="CNY",
        options=[
            {"id": "control", "label": "保持原详情页"},
            {"id": "treatment", "label": "使用新版详情页"},
        ],
        evidence_ids=[evidence_id],
        requested_by="operator-1",
    )
    analysis = decisions.submit_analysis(
        contract["id"],
        conclusion="证据不足以全量上线，应进行受控随机实验",
        confidence=Decimal("0.65"),
        recommended_option_id="treatment",
        forecast_metric="cm3_per_visitor",
        forecast_value=Decimal("110"),
        forecast_low=Decimal("100"),
        forecast_high=Decimal("120"),
        forecast_unit="CNY",
        forecast_due_at="2026-07-31T00:00:00+00:00",
        evidence_ids=[evidence_id],
        submitted_by="analyst-1",
    )
    decisions.review_analysis(
        analysis["id"],
        verdict="accepted",
        rationale="允许在预算和止损线内验证",
        evidence_ids=[evidence_id],
        reviewed_by="reviewer-2",
    )
    return decisions.resolve(
        contract["id"],
        analysis_id=analysis["id"],
        disposition="experiment",
        rationale="先实验，结果必须独立复核",
        conditions=["禁止自动放量"],
        decided_by="approver-3",
    )


def register(experiments, resolution_id, evidence_id):
    return experiments.register(
        resolution_id,
        hypothesis="新版详情页提高每访客贡献利润",
        primary_metric="cm3_per_visitor",
        randomization_unit="visitor",
        interference_cluster="product_family",
        variants=[
            {
                "id": "control",
                "label": "原详情页",
                "allocation": "0.5",
                "control": True,
            },
            {
                "id": "treatment",
                "label": "新版详情页",
                "allocation": "0.5",
                "control": False,
            },
        ],
        target_sample_size=20,
        minimum_detectable_effect=Decimal("5"),
        budget_cap_amount=Decimal("1000"),
        stop_loss_amount=Decimal("300"),
        currency="CNY",
        start_at="2026-07-18T00:00:00+00:00",
        end_at="2026-07-25T00:00:00+00:00",
        outcome_window_days=7,
        guardrails=[
            {"metric": "refund_rate", "direction": "max", "threshold": "0.1"}
        ],
        evidence_ids=[evidence_id],
        created_by="experiment-owner",
    )


def start(experiments, protocol_id, evidence_id):
    return experiments.transition(
        protocol_id,
        event_type="started",
        effective_at="2026-07-18T00:00:00+00:00",
        evidence_id=evidence_id,
        reason="预注册检查完成",
        created_by="approver-3",
    )


def test_protocol_is_immutable_idempotent_and_seed_is_private():
    _, evidence, contracts, decisions, experiments = setup_services()
    source = capture(evidence, "protocol")
    resolution = experiment_resolution(contracts, decisions, source.id)
    protocol = register(experiments, resolution["id"], source.id)
    retry = register(experiments, resolution["id"], source.id)

    assert retry["id"] == protocol["id"]
    assert protocol["status"] == "registered"
    assert "assignment_seed" not in protocol
    assert protocol["variants"][0]["allocation"] == "0.5"
    assert evidence.target_evidence_ids(
        target_type="causal_experiment_protocol",
        target_id=protocol["id"],
    ) == [source.id]

    with pytest.raises(ValueError, match="immutable experiment protocol"):
        experiments.register(
            resolution["id"],
            hypothesis="事后修改假设",
            primary_metric="cm3_per_visitor",
            randomization_unit="visitor",
            variants=protocol["variants"],
            target_sample_size=20,
            minimum_detectable_effect=Decimal("5"),
            budget_cap_amount=Decimal("1000"),
            stop_loss_amount=Decimal("300"),
            currency="CNY",
            start_at=protocol["start_at"],
            end_at=protocol["end_at"],
            guardrails=protocol["guardrails"],
            evidence_ids=[source.id],
            created_by="experiment-owner",
        )


def test_lifecycle_and_assignment_are_idempotent_and_privacy_preserving():
    _, evidence, contracts, decisions, experiments = setup_services()
    source = capture(evidence, "assignment")
    resolution = experiment_resolution(contracts, decisions, source.id)
    protocol = register(experiments, resolution["id"], source.id)

    with pytest.raises(ValueError, match="running status"):
        experiments.assign(
            protocol["id"],
            unit_key="raw-customer-123",
            assigned_at="2026-07-18T01:00:00+00:00",
        )
    started = start(experiments, protocol["id"], source.id)
    retried = start(experiments, protocol["id"], source.id)
    assert retried["events"] == started["events"]
    assert len(started["events"]) == 1

    assigned = experiments.assign(
        protocol["id"],
        unit_key="raw-customer-123",
        assigned_at="2026-07-18T01:00:00+00:00",
    )
    retry = experiments.assign(
        protocol["id"],
        unit_key="raw-customer-123",
        assigned_at="2026-07-19T01:00:00+00:00",
    )
    assert retry["id"] == assigned["id"]
    assert retry["variant_id"] == assigned["variant_id"]
    assert retry["unit_hash"] != "raw-customer-123"
    assert len(retry["unit_hash"]) == 64

    experiments.transition(
        protocol["id"],
        event_type="paused",
        effective_at="2026-07-19T02:00:00+00:00",
        evidence_id=source.id,
        reason="检查护栏",
        created_by="approver-3",
    )
    with pytest.raises(ValueError, match="chronological"):
        experiments.transition(
            protocol["id"],
            event_type="resumed",
            effective_at="2026-07-19T01:00:00+00:00",
            evidence_id=source.id,
            reason="时间倒流",
            created_by="approver-3",
        )


def test_results_require_independent_review_and_never_auto_roll_out():
    _, evidence, contracts, decisions, experiments = setup_services()
    source = capture(evidence, "results")
    resolution = experiment_resolution(contracts, decisions, source.id)
    protocol = register(experiments, resolution["id"], source.id)
    start(experiments, protocol["id"], source.id)

    observed_by_variant = {"control": 0, "treatment": 0}
    for index in range(200):
        assignment = experiments.assign(
            protocol["id"],
            unit_key=f"visitor-{index}",
            assigned_at="2026-07-19T00:00:00+00:00",
        )
        variant = assignment["variant_id"]
        if observed_by_variant[variant] >= 10:
            continue
        baseline = Decimal("100") if variant == "control" else Decimal("110")
        value = baseline + Decimal(observed_by_variant[variant] % 2)
        saved = experiments.observe(
            assignment["id"],
            value=value,
            observed_at="2026-07-26T00:00:00+00:00",
            evidence_id=source.id,
            created_by="finance-1",
        )
        retry = experiments.observe(
            assignment["id"],
            value=value,
            observed_at="2026-07-26T00:00:00+00:00",
            evidence_id=source.id,
            created_by="finance-1",
        )
        assert retry["id"] == saved["id"]
        observed_by_variant[variant] += 1
        if observed_by_variant == {"control": 10, "treatment": 10}:
            break

    result = experiments.evaluate(protocol["id"])
    assert observed_by_variant == {"control": 10, "treatment": 10}
    assert result["status"] == "ready_for_independent_review"
    assert result["review_eligible"] is True
    assert result["decision_eligible"] is False
    assert result["automatic_rollout"] is False
    assert Decimal(result["treatment_effect"]["absolute_effect"]) == Decimal("10")
    assert result["interpretation"] == "RESULT_REQUIRES_INDEPENDENT_REVIEW"

    first_assignment = experiments.assign(
        protocol["id"],
        unit_key="immutable-outcome",
        assigned_at="2026-07-20T00:00:00+00:00",
    )
    experiments.observe(
        first_assignment["id"],
        value=Decimal("1"),
        observed_at="2026-07-26T00:00:00+00:00",
        evidence_id=source.id,
        created_by="finance-1",
    )
    with pytest.raises(ValueError, match="immutable primary outcome"):
        experiments.observe(
            first_assignment["id"],
            value=Decimal("2"),
            observed_at="2026-07-26T00:00:00+00:00",
            evidence_id=source.id,
            created_by="finance-1",
        )


def test_sample_ratio_mismatch_blocks_interpretation():
    engine, evidence, contracts, decisions, experiments = setup_services()
    source = capture(evidence, "srm")
    resolution = experiment_resolution(contracts, decisions, source.id)
    protocol = register(experiments, resolution["id"], source.id)
    start(experiments, protocol["id"], source.id)
    with Session(engine) as session:
        row = session.scalar(
            select(ExperimentProtocolRow).where(
                ExperimentProtocolRow.id == protocol["id"]
            )
        )
        assert row is not None
        seed = row.assignment_seed

    selected = []
    for index in range(10000):
        key = f"filtered-visitor-{index}"
        bucket = int(
            hmac.new(
                seed.encode(),
                f"variant:{key}".encode(),
                hashlib.sha256,
            ).hexdigest(),
            16,
        ) / (2**256)
        if bucket < 0.5:
            selected.append(key)
        if len(selected) == 20:
            break
    assert len(selected) == 20
    for key in selected:
        assignment = experiments.assign(
            protocol["id"],
            unit_key=key,
            assigned_at="2026-07-19T00:00:00+00:00",
        )
        assert assignment["variant_id"] == "control"

    result = experiments.evaluate(protocol["id"])
    assert result["status"] == "invalid_sample_ratio"
    assert result["sample_ratio_mismatch"] is True
    assert result["review_eligible"] is False
    assert result["decision_eligible"] is False
    assert result["interpretation"] == "SRM_BLOCKS_DECISION"


def test_budget_stop_loss_and_guardrails_freeze_new_assignments():
    _, evidence, contracts, decisions, experiments = setup_services()
    source = capture(evidence, "safety")
    resolution = experiment_resolution(contracts, decisions, source.id)
    protocol = register(experiments, resolution["id"], source.id)
    start(experiments, protocol["id"], source.id)
    existing = experiments.assign(
        protocol["id"],
        unit_key="existing-before-breach",
        assigned_at="2026-07-19T00:00:00+00:00",
    )

    safe = experiments.record_safety_check(
        protocol["id"],
        metric="budget_spend_amount",
        value=Decimal("900"),
        observed_at="2026-07-19T01:00:00+00:00",
        evidence_id=source.id,
        created_by="finance-1",
    )
    assert safe["status"] == "within_limit"
    breached = experiments.record_safety_check(
        protocol["id"],
        metric="refund_rate",
        value=Decimal("0.11"),
        observed_at="2026-07-19T02:00:00+00:00",
        evidence_id=source.id,
        created_by="risk-1",
    )
    retry = experiments.record_safety_check(
        protocol["id"],
        metric="refund_rate",
        value=Decimal("0.11"),
        observed_at="2026-07-19T02:00:00+00:00",
        evidence_id=source.id,
        created_by="risk-1",
    )
    assert retry["id"] == breached["id"]
    assert breached["status"] == "breached"
    assert experiments.assign(
        protocol["id"],
        unit_key="existing-before-breach",
        assigned_at="2026-07-20T00:00:00+00:00",
    )["id"] == existing["id"]
    with pytest.raises(ValueError, match="safety gate is breached"):
        experiments.assign(
            protocol["id"],
            unit_key="new-after-breach",
            assigned_at="2026-07-20T00:00:00+00:00",
        )

    result = experiments.evaluate(protocol["id"])
    assert result["status"] == "safety_breach"
    assert result["safety_gate_breached"] is True
    assert result["review_eligible"] is False
    assert result["automatic_rollout"] is False
    assert result["interpretation"] == "SAFETY_BREACH_FREEZES_ASSIGNMENT"

    with pytest.raises(ValueError, match="not a preregistered safety guardrail"):
        experiments.record_safety_check(
            protocol["id"],
            metric="sales_volume",
            value=Decimal("100"),
            observed_at="2026-07-19T03:00:00+00:00",
            evidence_id=source.id,
            created_by="operator-1",
        )


def test_registration_rejects_unsafe_or_ambiguous_protocols():
    _, evidence, contracts, decisions, experiments = setup_services()
    source = capture(evidence, "unsafe")
    resolution = experiment_resolution(contracts, decisions, source.id)
    with pytest.raises(ValueError, match="exactly two variants"):
        experiments.register(
            resolution["id"],
            hypothesis="ambiguous",
            primary_metric="profit",
            randomization_unit="visitor",
            variants=[
                {"id": "only", "label": "only", "allocation": "1", "control": True}
            ],
            target_sample_size=20,
            minimum_detectable_effect=Decimal("1"),
            budget_cap_amount=Decimal("100"),
            stop_loss_amount=Decimal("10"),
            currency="CNY",
            start_at="2026-07-18T00:00:00+00:00",
            end_at="2026-07-25T00:00:00+00:00",
            guardrails=[
                {"metric": "refund", "direction": "max", "threshold": "0.1"}
            ],
            evidence_ids=[source.id],
            created_by="owner",
        )

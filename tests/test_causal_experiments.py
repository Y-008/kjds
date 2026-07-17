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
from apps.control_plane.causal_knowledge import CausalKnowledgeService
from apps.control_plane.causal_policies import CausalPolicyService
from apps.control_plane.decision_contracts import DecisionContractService
from apps.control_plane.decision_lifecycle import DecisionLifecycleService
from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.policy_shadow import PolicyShadowService
from apps.control_plane.repository import InMemoryRepository
from apps.control_plane.services import CommerceService
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


def experiment_resolution(contracts, decisions, evidence_id, objective_suffix=""):
    contract = contracts.create(
        profile="/x10think",
        objective=f"验证新版详情页是否提高每访客贡献利润{objective_suffix}",
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


def register(
    experiments,
    resolution_id,
    evidence_id,
    *,
    stratification_keys=None,
    effect_metrics=None,
):
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
        stratification_keys=stratification_keys or [],
        effect_metrics=effect_metrics or [],
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


def populate_ready_experiment(experiments, protocol_id, evidence_id, unit_prefix="knowledge"):
    start(experiments, protocol_id, evidence_id)
    with Session(experiments.engine) as session:
        protocol_row = session.get(ExperimentProtocolRow, protocol_id)
        assert protocol_row is not None
        seed = protocol_row.assignment_seed
    selected = {"control": [], "treatment": []}
    for index in range(500):
        unit_key = f"{unit_prefix}-{index}"
        bucket = int(
            hmac.new(
                seed.encode(),
                f"variant:{unit_key}".encode(),
                hashlib.sha256,
            ).hexdigest(),
            16,
        ) / (2**256)
        variant = "control" if bucket < 0.5 else "treatment"
        if len(selected[variant]) < 10:
            selected[variant].append(unit_key)
        if all(len(items) == 10 for items in selected.values()):
            break
    assert all(len(items) == 10 for items in selected.values())
    counts = {"control": 0, "treatment": 0}
    for expected_variant, unit_keys in selected.items():
        for unit_key in unit_keys:
            assignment = experiments.assign(
                protocol_id,
                unit_key=unit_key,
                assigned_at="2026-07-19T00:00:00+00:00",
            )
            assert assignment["variant_id"] == expected_variant
            experiments.observe(
                assignment["id"],
                value=(
                    Decimal("100")
                    if expected_variant == "control"
                    else Decimal("110")
                ),
                observed_at="2026-07-26T00:00:00+00:00",
                evidence_id=evidence_id,
                created_by="finance-1",
            )
            counts[expected_variant] += 1
    assert counts == {"control": 10, "treatment": 10}
    assert experiments.evaluate(protocol_id)["review_eligible"] is True


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


def test_preregistered_segments_and_full_value_model_prevent_local_optimization():
    _, evidence, contracts, decisions, experiments = setup_services()
    source = capture(evidence, "value-model")
    resolution = experiment_resolution(contracts, decisions, source.id)
    protocol = register(
        experiments,
        resolution["id"],
        source.id,
        stratification_keys=["country_tier"],
        effect_metrics=[
            {
                "metric": "cannibalized_cm3",
                "role": "cannibalization",
                "multiplier": "-1",
                "required": True,
            },
            {
                "metric": "refund_cost_30d",
                "role": "long_term_cost",
                "multiplier": "-1",
                "required": True,
            },
        ],
    )
    start(experiments, protocol["id"], source.id)
    counts = {
        (variant, tier): 0
        for variant in ("control", "treatment")
        for tier in ("tier_1", "tier_2")
    }
    first_assignment = None
    for index in range(500):
        tier = "tier_1" if index % 2 == 0 else "tier_2"
        assignment = experiments.assign(
            protocol["id"],
            unit_key=f"segmented-visitor-{index}",
            assigned_at="2026-07-19T00:00:00+00:00",
            strata={"country_tier": tier},
        )
        if first_assignment is None:
            first_assignment = assignment
        key = (assignment["variant_id"], tier)
        if counts[key] >= 5:
            continue
        if assignment["variant_id"] == "control":
            primary_value = Decimal("100")
            cannibalization = Decimal("0")
            long_term_cost = Decimal("0")
        else:
            primary_value = Decimal("120") if tier == "tier_1" else Decimal("110")
            cannibalization = Decimal("5")
            long_term_cost = Decimal("2")
        for metric, value in (
            ("cm3_per_visitor", primary_value),
            ("cannibalized_cm3", cannibalization),
            ("refund_cost_30d", long_term_cost),
        ):
            experiments.observe(
                assignment["id"],
                metric=metric,
                value=value,
                observed_at="2026-07-26T00:00:00+00:00",
                evidence_id=source.id,
                created_by="finance-1",
            )
        counts[key] += 1
        if all(value == 5 for value in counts.values()):
            break

    assert all(value == 5 for value in counts.values())
    assert first_assignment is not None
    with pytest.raises(ValueError, match="immutable strata"):
        experiments.assign(
            protocol["id"],
            unit_key="segmented-visitor-0",
            assigned_at="2026-07-20T00:00:00+00:00",
            strata={"country_tier": "changed_after_assignment"},
        )

    result = experiments.evaluate(protocol["id"])
    assert result["status"] == "ready_for_independent_review"
    assert result["missing_required_metrics"] == []
    assert Decimal(result["treatment_effect"]["absolute_effect"]) == Decimal("15")
    assert Decimal(result["incremental_value_per_unit"]) == Decimal("8")
    metric_effects = {
        item["metric"]: Decimal(item["effect"]["absolute_effect"])
        for item in result["effect_metric_results"]
    }
    assert metric_effects == {
        "cm3_per_visitor": Decimal("15"),
        "cannibalized_cm3": Decimal("5"),
        "refund_cost_30d": Decimal("2"),
    }
    strata = result["heterogeneous_effects"][0]
    assert strata["key"] == "country_tier"
    segment_effects = {
        item["value"]: Decimal(item["effect"]["absolute_effect"])
        for item in strata["segments"]
    }
    assert segment_effects == {"tier_1": Decimal("20"), "tier_2": Decimal("10")}


def test_missing_required_long_term_metric_blocks_review():
    _, evidence, contracts, decisions, experiments = setup_services()
    source = capture(evidence, "incomplete-value-model")
    resolution = experiment_resolution(contracts, decisions, source.id)
    protocol = register(
        experiments,
        resolution["id"],
        source.id,
        effect_metrics=[
            {
                "metric": "refund_cost_30d",
                "role": "long_term_cost",
                "multiplier": "-1",
                "required": True,
            }
        ],
    )
    start(experiments, protocol["id"], source.id)
    counts = {"control": 0, "treatment": 0}
    for index in range(200):
        assignment = experiments.assign(
            protocol["id"],
            unit_key=f"long-term-pending-{index}",
            assigned_at="2026-07-19T00:00:00+00:00",
        )
        variant = assignment["variant_id"]
        if counts[variant] >= 10:
            continue
        experiments.observe(
            assignment["id"],
            value=Decimal("100") if variant == "control" else Decimal("110"),
            observed_at="2026-07-20T00:00:00+00:00",
            evidence_id=source.id,
            created_by="finance-1",
        )
        counts[variant] += 1
        if counts == {"control": 10, "treatment": 10}:
            break

    result = experiments.evaluate(protocol["id"])
    assert result["status"] == "incomplete_value_model"
    assert result["review_eligible"] is False
    assert result["missing_required_metrics"] == ["refund_cost_30d"]
    assert result["incremental_value_per_unit"] is None


def test_causal_knowledge_requires_independent_review_and_invalidates_on_new_risk():
    engine, evidence, contracts, decisions, experiments = setup_services()
    knowledge = CausalKnowledgeService(
        engine=engine,
        experiments=experiments,
        evidence=evidence,
    )
    source = capture(evidence, "causal-knowledge")
    resolution = experiment_resolution(contracts, decisions, source.id, "-knowledge")
    protocol = register(experiments, resolution["id"], source.id)
    populate_ready_experiment(experiments, protocol["id"], source.id)

    with pytest.raises(ValueError, match="owner cannot independently review"):
        knowledge.review_experiment(
            protocol["id"],
            verdict="accepted",
            rationale="结果支持预注册假设",
            method_assessment="随机化与干扰边界可接受",
            data_quality_assessment="样本比例和数据完整性通过",
            counterarguments=["可能存在平台算法的迟滞放大"],
            evidence_ids=[source.id],
            reviewed_by="experiment-owner",
        )

    review = knowledge.review_experiment(
        protocol["id"],
        verdict="accepted",
        rationale="结果支持预注册假设，但只适用于登记范围",
        method_assessment="随机化、样本比例和干扰边界可接受",
        data_quality_assessment="主指标样本完整且无SRM",
        counterarguments=["平台算法反馈可能解释部分效果"],
        evidence_ids=[source.id],
        reviewed_by="causal-reviewer-1",
    )
    retry = knowledge.review_experiment(
        protocol["id"],
        verdict="accepted",
        rationale="结果支持预注册假设，但只适用于登记范围",
        method_assessment="随机化、样本比例和干扰边界可接受",
        data_quality_assessment="主指标样本完整且无SRM",
        counterarguments=["平台算法反馈可能解释部分效果"],
        evidence_ids=[source.id],
        reviewed_by="causal-reviewer-1",
    )
    assert retry["id"] == review["id"]
    assert review["immutable"] is True

    entry = knowledge.publish(
        protocol["id"],
        review_id=review["id"],
        claim="新版详情页提高每访客贡献利润",
        mechanism="更清晰的价值表达降低理解成本并提高合格转化",
        applicability={
            "platform": "Ozon",
            "country": "RU",
            "category": "test-category",
            "population": "eligible-visitors",
        },
        falsification_conditions=[
            "后续复现实验效果方向相反",
            "任何预注册安全护栏被突破",
        ],
        evidence_ids=[source.id],
        valid_from="2026-07-17T00:00:00+00:00",
        reevaluate_at="2027-07-17T00:00:00+00:00",
        created_by="knowledge-approver-1",
    )
    assert entry["validity_status"] == "active"
    assert entry["usable"] is True
    assert entry["knowledge_strength"] == "provisional"
    assert entry["execution_eligible"] is False
    assert entry["automatic_rollout"] is False

    experiments.record_safety_check(
        protocol["id"],
        metric="refund_rate",
        value=Decimal("0.11"),
        observed_at="2026-07-27T00:00:00+00:00",
        evidence_id=source.id,
        created_by="risk-1",
    )
    invalidated = knowledge.get(entry["id"])
    assert invalidated["validity_status"] == "source_experiment_invalidated"
    assert invalidated["usable"] is False
    assert knowledge.list(usable_only=True) == []


def test_independent_replication_upgrades_strength_without_granting_execution_rights():
    engine, evidence, contracts, decisions, experiments = setup_services()
    knowledge = CausalKnowledgeService(
        engine=engine,
        experiments=experiments,
        evidence=evidence,
    )
    source = capture(evidence, "causal-replication")
    applicability = {
        "platform": "Ozon",
        "country": "RU",
        "category": "test-category",
        "population": "eligible-visitors",
    }
    published = []
    for index in (1, 2):
        resolution = experiment_resolution(
            contracts,
            decisions,
            source.id,
            f"-replication-{index}",
        )
        protocol = register(experiments, resolution["id"], source.id)
        populate_ready_experiment(
            experiments,
            protocol["id"],
            source.id,
            unit_prefix=f"replication-{index}",
        )
        review = knowledge.review_experiment(
            protocol["id"],
            verdict="accepted",
            rationale="独立实验支持相同方向的效果",
            method_assessment="预注册随机实验设计通过",
            data_quality_assessment="无SRM且指标完整",
            counterarguments=["季节性仍可能限制结论迁移"],
            evidence_ids=[source.id],
            reviewed_by=f"causal-reviewer-{index}",
        )
        published.append(
            knowledge.publish(
                protocol["id"],
                review_id=review["id"],
                claim="新版详情页提高每访客贡献利润",
                mechanism="更清晰的价值表达降低理解成本并提高合格转化",
                applicability=applicability,
                falsification_conditions=["复现实验效果方向相反"],
                evidence_ids=[source.id],
                valid_from="2026-07-17T00:00:00+00:00",
                reevaluate_at="2027-07-17T00:00:00+00:00",
                created_by=f"knowledge-approver-{index}",
                replicates_knowledge_id=published[0]["id"] if published else None,
                replication_rationale=(
                    "以独立协议在相同适用范围复现" if published else None
                ),
            )
        )

    root = knowledge.get(published[0]["id"])
    replication = knowledge.get(published[1]["id"])
    assert root["knowledge_strength"] == "replicated"
    assert root["usable_replication_count"] == 1
    assert replication["replication_of"]["source_knowledge_id"] == root["id"]
    assert root["execution_eligible"] is False


def test_usable_knowledge_compiles_to_conditional_policy_with_staged_promotion_gates():
    engine, evidence, contracts, decisions, experiments = setup_services()
    knowledge = CausalKnowledgeService(
        engine=engine,
        experiments=experiments,
        evidence=evidence,
    )
    policies = CausalPolicyService(
        engine=engine,
        knowledge=knowledge,
        evidence=evidence,
    )
    source = capture(evidence, "causal-policy")
    resolution = experiment_resolution(contracts, decisions, source.id, "-policy")
    protocol = register(experiments, resolution["id"], source.id)
    populate_ready_experiment(experiments, protocol["id"], source.id, "policy")
    experiment_review = knowledge.review_experiment(
        protocol["id"],
        verdict="accepted",
        rationale="独立实验支持有限范围内的策略候选",
        method_assessment="预注册随机实验设计通过",
        data_quality_assessment="样本和SRM质量门通过",
        counterarguments=["库存状态改变时效果可能不成立"],
        evidence_ids=[source.id],
        reviewed_by="causal-reviewer",
    )
    applicability = {
        "platform": "Ozon",
        "country": "RU",
        "category": "test-category",
        "population": "eligible-visitors",
    }
    entry = knowledge.publish(
        protocol["id"],
        review_id=experiment_review["id"],
        claim="新版详情页提高每访客贡献利润",
        mechanism="更清晰的价值表达降低理解成本并提高合格转化",
        applicability=applicability,
        falsification_conditions=["安全护栏越线", "独立复现方向相反"],
        evidence_ids=[source.id],
        valid_from="2026-07-17T00:00:00+00:00",
        reevaluate_at="2027-07-17T00:00:00+00:00",
        created_by="knowledge-publisher",
    )

    policy = policies.propose(
        title="库存充足时建议使用已验证详情页",
        objective="只在适用边界和库存安全条件内建议候选页面",
        knowledge_ids=[entry["id"]],
        applicability=applicability,
        conditions=[{"field": "inventory_cover_days", "operator": "gte", "value": 45}],
        action={"type": "recommend_listing_change", "parameters": {"variant": "treatment"}},
        guardrails=[{"metric": "refund_rate", "direction": "max", "threshold": "0.1"}],
        fallback_action={"type": "recommend_no_action", "parameters": {"reason": "conditions_not_met"}},
        rollout_stages=[
            {
                "name": "shadow",
                "max_exposure_fraction": "0",
                "minimum_observation_count": 20,
                "minimum_incremental_value": "0",
            },
            {
                "name": "limited_10_percent",
                "max_exposure_fraction": "0.1",
                "minimum_observation_count": 100,
                "minimum_incremental_value": "3",
            },
        ],
        evidence_ids=[source.id],
        proposed_by="policy-proposer",
    )
    matched = policies.evaluate_context(
        policy["id"],
        {**applicability, "inventory_cover_days": 60},
    )
    assert matched["matched"] is True
    assert matched["recommendation"]["type"] == "recommend_listing_change"
    assert matched["execution_eligible"] is False

    with pytest.raises(ValueError, match="proposer cannot independently review"):
        policies.review(
            policy["id"],
            verdict="accepted",
            rationale="自审必须失败",
            counterarguments=["风险"],
            evidence_ids=[source.id],
            reviewed_by="policy-proposer",
        )
    policy_review = policies.review(
        policy["id"],
        verdict="accepted",
        rationale="条件、退回动作和护栏均明确",
        counterarguments=["平台流量结构变化可能使知识失效"],
        evidence_ids=[source.id],
        reviewed_by="policy-reviewer",
    )
    shadow = policies.release_stage(
        policy["id"],
        review_id=policy_review["id"],
        stage_index=0,
        rationale="先进入零暴露影子观察",
        evidence_ids=[source.id],
        approved_by="policy-approver",
    )
    assert shadow["stage"]["max_exposure_fraction"] == "0"
    assert shadow["execution_eligible"] is False
    commerce = CommerceService(
        InMemoryRepository(),
        evidence_validator=evidence.require_valid,
    )
    shadow_service = PolicyShadowService(
        engine=engine,
        policies=policies,
        evidence=evidence,
        commerce=commerce,
    )
    with pytest.raises(ValueError, match="preregistered number"):
        shadow_service.validate_stage_outcome(shadow["id"], 20)
    contexts = [
        {**applicability, "inventory_cover_days": 60 if index < 12 else 30}
        for index in range(20)
    ]
    batch = shadow_service.run_shadow_batch(
        shadow["id"],
        batch_key="shadow-2026-07-17",
        contexts=contexts,
        observed_at="2026-07-17T12:00:00+00:00",
        evidence_ids=[source.id],
        created_by="shadow-operator",
    )
    assert batch["zero_exposure"] is True
    assert batch["execution_eligible"] is False
    assert batch["matched_count"] == 12
    assert batch["fallback_count"] == 8
    shadow_service.validate_stage_outcome(shadow["id"], 20)
    with pytest.raises(ValueError, match="must equal"):
        shadow_service.validate_stage_outcome(shadow["id"], 19)
    assert (
        shadow_service.run_shadow_batch(
            shadow["id"],
            batch_key="shadow-2026-07-17",
            contexts=contexts,
            observed_at="2026-07-17T12:00:00+00:00",
            evidence_ids=[source.id],
            created_by="shadow-operator",
        )["id"]
        == batch["id"]
    )
    with pytest.raises(ValueError, match="Sensitive field"):
        shadow_service.record_evaluation(
            shadow["id"],
            idempotency_key="sensitive-context",
            context={**applicability, "customer_email": "forbidden@example.com"},
            observed_at="2026-07-17T12:00:00+00:00",
            evidence_ids=[source.id],
            evaluated_by="shadow-operator",
        )
    with pytest.raises(ValueError, match="zero-exposure shadow stage"):
        shadow_service.request_activation(
            shadow["id"],
            evaluation_ids=batch["evaluation_ids"],
            evidence_ids=[source.id],
            requested_by="activation-requester",
        )
    with pytest.raises(ValueError, match="needs a recorded outcome"):
        policies.release_stage(
            policy["id"],
            review_id=policy_review["id"],
            stage_index=1,
            rationale="不可跳过结果门",
            evidence_ids=[source.id],
            approved_by="policy-approver",
        )
    outcome = policies.record_stage_outcome(
        shadow["id"],
        verdict="passed",
        observation_count=20,
        incremental_value=Decimal("3"),
        guardrail_breached=False,
        notes="影子阶段没有安全异常，结果达到门槛",
        evidence_ids=[source.id],
        recorded_by="outcome-recorder",
    )
    assert outcome["verdict"] == "passed"
    limited = policies.release_stage(
        policy["id"],
        review_id=policy_review["id"],
        stage_index=1,
        rationale="上一阶段结果达到预注册晋级门槛",
        evidence_ids=[source.id],
        approved_by="policy-approver",
    )
    assert limited["stage"]["max_exposure_fraction"] == "0.1"
    assert limited["automatic_promotion"] is False
    handoff = shadow_service.request_activation(
        limited["id"],
        evaluation_ids=batch["evaluation_ids"],
        evidence_ids=[source.id],
        requested_by="activation-requester",
    )
    assert handoff["approval_status"] == "pending"
    assert handoff["activation_eligible"] is False
    assert handoff["execution_eligible"] is False
    with pytest.raises(ValueError, match="Requester cannot approve"):
        commerce.decide_approval(
            handoff["approval_id"],
            approved=True,
            decided_by="activation-requester",
            reason="自批必须失败",
        )
    commerce.decide_approval(
        handoff["approval_id"],
        approved=True,
        decided_by="independent-approver",
        reason="证据和影子批次通过独立复核",
    )
    approved_handoff = shadow_service.get_handoff(handoff["id"])
    assert approved_handoff["activation_eligible"] is True
    assert approved_handoff["execution_eligible"] is False

    experiments.record_safety_check(
        protocol["id"],
        metric="refund_rate",
        value=Decimal("0.11"),
        observed_at="2026-07-27T00:00:00+00:00",
        evidence_id=source.id,
        created_by="risk-1",
    )
    invalidated = policies.get(policy["id"])
    assert invalidated["validity_status"] == "source_knowledge_invalidated"
    invalidated_handoff = shadow_service.get_handoff(handoff["id"])
    assert invalidated_handoff["validity_status"] == "source_policy_invalidated"
    assert invalidated_handoff["activation_eligible"] is False
    after_invalidation = policies.evaluate_context(
        policy["id"],
        {**applicability, "inventory_cover_days": 60},
    )
    assert after_invalidation["matched"] is False
    assert after_invalidation["recommendation"]["type"] == "recommend_no_action"


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

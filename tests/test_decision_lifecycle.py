from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

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
    lifecycle = DecisionLifecycleService(
        engine=engine,
        contracts=contracts,
        evidence=evidence,
    )
    return evidence, contracts, lifecycle


def capture(evidence: EvidenceService, ref: str):
    return evidence.capture(
        content=f"immutable evidence for {ref}".encode(),
        filename=f"{ref}.txt",
        content_type="text/plain",
        source="decision_lifecycle_test",
        source_ref=f"test://{ref}",
        grade=EvidenceGrade.A,
        effective_at="2026-07-17T00:00:00+00:00",
        effective_until=None,
        created_by="tester",
    )


def decision_contract(contracts, evidence_id, *, risk="high"):
    return contracts.create(
        profile="/x10think",
        objective="选择首批样品数量",
        decision_domain="procurement",
        risk_level=risk,
        maximum_loss_amount=Decimal("30000"),
        currency="CNY",
        options=[
            {"id": "A", "label": "采购100件"},
            {"id": "B", "label": "暂不采购"},
        ],
        evidence_ids=[evidence_id],
        requested_by="operator-1",
    )


def analysis(lifecycle, contract_id, evidence_id, *, submitted_by="analyst-1"):
    return lifecycle.submit_analysis(
        contract_id,
        conclusion="小批量方案下行风险可控，建议选择 A",
        confidence=Decimal("0.72"),
        recommended_option_id="A",
        forecast_metric="sample_cm3_cny",
        forecast_value=Decimal("12000"),
        forecast_low=Decimal("5000"),
        forecast_high=Decimal("18000"),
        forecast_unit="CNY",
        forecast_due_at="2026-07-18T00:00:00+00:00",
        assumptions=["物流费率保持稳定"],
        unknowns=["首批真实退货率"],
        evidence_ids=[evidence_id],
        model_ref="qwen-test-version",
        submitted_by=submitted_by,
    )


def best_solution_contract(contracts, evidence_id):
    return contracts.create(
        profile="/best",
        objective="选择 Ozon 财务事实来源",
        decision_domain="architecture",
        risk_level="medium",
        options=[
            {"id": "official", "label": "Ozon 官方原始报表"},
            {"id": "third-party", "label": "第三方计算器"},
            {"id": "no-action", "label": "暂不晋升财务事实"},
        ],
        context={
            "hard_constraints": ["原始证据可追溯", "不得自动入账"],
            "decision_criteria": ["长期价值", "总拥有成本", "可逆性"],
        },
        evidence_ids=[evidence_id],
        requested_by="operator-1",
    )


def best_solution_assessment(*, selected="official"):
    option_ids = ["official", "third-party", "no-action"]
    constraints = ["原始证据可追溯", "不得自动入账"]
    return {
        "hard_constraint_results": [
            {
                "option_id": option_id,
                "constraint": constraint,
                "passed": option_id != "third-party" or constraint == "不得自动入账",
                "rationale": f"{option_id} 对 {constraint} 的证据判断",
            }
            for option_id in option_ids
            for constraint in constraints
        ],
        "option_assessments": [
            {
                "option_id": option_id,
                "evidence_quality": "A" if option_id == "official" else "C",
                "expected_risk_adjusted_long_term_value": f"{option_id} 长期价值",
                "total_cost_of_ownership": f"{option_id} 总拥有成本",
                "maximum_loss": f"{option_id} 最大损失",
                "reversibility_and_rollback": f"{option_id} 回滚方案",
                "time_to_value": f"{option_id} 落地时间",
                "operational_fit": f"{option_id} 运维适配",
            }
            for option_id in option_ids
        ],
        "rejected_options": [
            {"option_id": option_id, "reason": f"未选择 {option_id} 的原因"}
            for option_id in option_ids
            if option_id != selected
        ],
        "sensitivity_drivers": ["官方字段或账单口径变化"],
        "invalidation_conditions": ["无法复核原始报表哈希"],
        "review_at": "2026-08-20T00:00:00+00:00",
        "approval_requirement": "独立复核后由负责人批准",
        "no_action_option_id": "no-action",
        "no_action_omission_reason": None,
    }


def test_full_decision_lifecycle_is_separated_idempotent_and_calibrated():
    evidence, contracts, lifecycle = setup_services()
    source = capture(evidence, "analysis")
    outcome_source = capture(evidence, "outcome")
    contract = decision_contract(contracts, source.id)
    submitted = analysis(lifecycle, contract["id"], source.id)
    retry = analysis(lifecycle, contract["id"], source.id)

    assert retry["id"] == submitted["id"]
    assert submitted["execution_eligible"] is False
    with pytest.raises(ValueError, match="cannot independently review"):
        lifecycle.review_analysis(
            submitted["id"],
            verdict="accepted",
            rationale="self review",
            evidence_ids=[source.id],
            reviewed_by="analyst-1",
        )

    review = lifecycle.review_analysis(
        submitted["id"],
        verdict="accepted",
        rationale="证据、区间和备选方案一致",
        counterarguments=["物流价格仍可能上升"],
        evidence_ids=[source.id],
        reviewed_by="reviewer-2",
    )
    resolution = lifecycle.resolve(
        contract["id"],
        analysis_id=submitted["id"],
        disposition="experiment",
        rationale="只按100件验证并保留停止条件",
        conditions=["最大损失不超过30000 CNY"],
        decided_by="reviewer-2",
    )
    with pytest.raises(ValueError, match="Actual outcome must be a finite number"):
        lifecycle.record_outcome(
            resolution["id"],
            actual_value=Decimal("NaN"),
            observed_at="2026-07-19T00:00:00+00:00",
            evidence_ids=[outcome_source.id],
            notes="无效数值不应进入结果账",
            recorded_by="finance-1",
        )
    outcome = lifecycle.record_outcome(
        resolution["id"],
        actual_value=Decimal("10000"),
        observed_at="2026-07-19T00:00:00+00:00",
        evidence_ids=[outcome_source.id],
        notes="样品签收并完成实际费用回填",
        recorded_by="finance-1",
    )

    assert review["verdict"] == "accepted"
    assert resolution["execution_eligible"] is False
    assert Decimal(outcome["signed_error"]) == Decimal("-2000")
    assert outcome["interval_covered"] is True
    calibration = lifecycle.calibration()[0]
    assert calibration["outcome_count"] == 1
    assert Decimal(calibration["mean_absolute_error"]) == Decimal("2000")
    assert calibration["interval_coverage"] == "1"
    assert evidence.target_evidence_ids(
        target_type="decision_outcome",
        target_id=outcome["id"],
    ) == [outcome_source.id]
    with pytest.raises(ValueError, match="Resolved analysis"):
        lifecycle.review_analysis(
            submitted["id"],
            verdict="accepted",
            rationale="late review",
            evidence_ids=[source.id],
            reviewed_by="reviewer-3",
        )
    with pytest.raises(ValueError, match="Resolved decision contract"):
        lifecycle.submit_analysis(
            contract["id"],
            conclusion="late competing analysis",
            confidence=Decimal("0.5"),
            recommended_option_id="B",
            forecast_metric="sample_cm3_cny",
            forecast_value=Decimal("0"),
            forecast_low=Decimal("-1000"),
            forecast_high=Decimal("1000"),
            forecast_unit="CNY",
            forecast_due_at="2026-07-20T00:00:00+00:00",
            evidence_ids=[source.id],
            submitted_by="analyst-2",
        )


def test_analysis_requires_registered_option_forecast_and_evidence():
    evidence, contracts, lifecycle = setup_services()
    source = capture(evidence, "requirements")
    contract = decision_contract(contracts, source.id)

    with pytest.raises(ValueError, match="registered option"):
        lifecycle.submit_analysis(
            contract["id"],
            conclusion="choose unknown option",
            confidence=Decimal("0.5"),
            recommended_option_id="Z",
            evidence_ids=[source.id],
            submitted_by="analyst",
        )
    with pytest.raises(ValueError, match="Forecast requires"):
        lifecycle.submit_analysis(
            contract["id"],
            conclusion="choose A without prediction",
            confidence=Decimal("0.5"),
            recommended_option_id="A",
            evidence_ids=[source.id],
            submitted_by="analyst",
        )

    with pytest.raises(ValueError, match="Analysis confidence must be a finite number"):
        lifecycle.submit_analysis(
            contract["id"],
            conclusion="invalid confidence",
            confidence=Decimal("NaN"),
            recommended_option_id="A",
            evidence_ids=[source.id],
            submitted_by="analyst",
        )

    with pytest.raises(ValueError, match="Forecast value must be a finite number"):
        lifecycle.submit_analysis(
            contract["id"],
            conclusion="invalid forecast",
            confidence=Decimal("0.5"),
            recommended_option_id="A",
            forecast_metric="sample_cm3_cny",
            forecast_value=Decimal("Infinity"),
            forecast_low=Decimal("0"),
            forecast_high=Decimal("100"),
            forecast_unit="CNY",
            forecast_due_at="2026-07-20T00:00:00+00:00",
            evidence_ids=[source.id],
            submitted_by="analyst",
        )


def test_blocking_review_prevents_resolution_and_review_is_immutable():
    evidence, contracts, lifecycle = setup_services()
    source = capture(evidence, "blocking")
    contract = decision_contract(contracts, source.id)
    submitted = analysis(lifecycle, contract["id"], source.id)
    lifecycle.review_analysis(
        submitted["id"],
        verdict="needs_revision",
        rationale="区间没有包含极端物流场景",
        counterarguments=["物流可能中断"],
        reviewed_by="reviewer-2",
    )

    with pytest.raises(ValueError, match="already submitted"):
        lifecycle.review_analysis(
            submitted["id"],
            verdict="accepted",
            rationale="changed mind",
            evidence_ids=[source.id],
            reviewed_by="reviewer-2",
        )
    with pytest.raises(ValueError, match="blocking independent review"):
        lifecycle.resolve(
            contract["id"],
            analysis_id=submitted["id"],
            disposition="adopt",
            rationale="try to bypass review",
            decided_by="approver-3",
        )


def test_critical_resolution_requires_two_reviewers_and_independent_decider():
    evidence, contracts, lifecycle = setup_services()
    source = capture(evidence, "critical")
    contract = decision_contract(contracts, source.id, risk="critical")
    submitted = analysis(lifecycle, contract["id"], source.id)
    for reviewer in ("reviewer-2", "reviewer-3"):
        lifecycle.review_analysis(
            submitted["id"],
            verdict="accepted",
            rationale=f"independent acceptance by {reviewer}",
            evidence_ids=[source.id],
            reviewed_by=reviewer,
        )

    with pytest.raises(ValueError, match="independent from reviewers"):
        lifecycle.resolve(
            contract["id"],
            analysis_id=submitted["id"],
            disposition="experiment",
            rationale="critical limited experiment",
            decided_by="reviewer-2",
        )
    resolution = lifecycle.resolve(
        contract["id"],
        analysis_id=submitted["id"],
        disposition="experiment",
        rationale="critical limited experiment",
        decided_by="approver-4",
    )
    assert resolution["decided_by"] == "approver-4"


def test_outcome_cannot_be_early_or_overwritten():
    evidence, contracts, lifecycle = setup_services()
    source = capture(evidence, "outcome-guard")
    contract = decision_contract(contracts, source.id)
    submitted = analysis(lifecycle, contract["id"], source.id)
    lifecycle.review_analysis(
        submitted["id"],
        verdict="accepted",
        rationale="accepted",
        evidence_ids=[source.id],
        reviewed_by="reviewer-2",
    )
    resolution = lifecycle.resolve(
        contract["id"],
        analysis_id=submitted["id"],
        disposition="adopt",
        rationale="adopt controlled path",
        decided_by="reviewer-2",
    )
    with pytest.raises(ValueError, match="before the registered forecast due date"):
        lifecycle.record_outcome(
            resolution["id"],
            actual_value=Decimal("10000"),
            observed_at="2026-07-17T12:00:00+00:00",
            evidence_ids=[source.id],
            notes="too early",
            recorded_by="finance-1",
        )
    saved = lifecycle.record_outcome(
        resolution["id"],
        actual_value=Decimal("10000"),
        observed_at="2026-07-19T00:00:00+00:00",
        evidence_ids=[source.id],
        notes="actual result",
        recorded_by="finance-1",
    )
    retry = lifecycle.record_outcome(
        resolution["id"],
        actual_value=Decimal("10000"),
        observed_at="2026-07-19T00:00:00+00:00",
        evidence_ids=[source.id],
        notes="actual result",
        recorded_by="finance-1",
    )
    assert retry["id"] == saved["id"]
    with pytest.raises(ValueError, match="already been recorded"):
        lifecycle.record_outcome(
            resolution["id"],
            actual_value=Decimal("11000"),
            observed_at="2026-07-20T00:00:00+00:00",
            evidence_ids=[source.id],
            notes="attempt overwrite",
            recorded_by="finance-1",
        )


def test_research_contract_can_be_analyzed_but_not_formally_resolved():
    evidence, contracts, lifecycle = setup_services()
    source = capture(evidence, "research")
    contract = contracts.create(
        profile="/truth",
        objective="核验平台规则变化",
        decision_domain="compliance",
        risk_level="medium",
        evidence_ids=[source.id],
        requested_by="operator-1",
    )
    submitted = lifecycle.submit_analysis(
        contract["id"],
        conclusion="证据只支持规则发生变化，不支持直接下架",
        confidence=Decimal("0.8"),
        evidence_ids=[source.id],
        submitted_by="analyst-1",
    )
    lifecycle.review_analysis(
        submitted["id"],
        verdict="accepted",
        rationale="证据链完整",
        evidence_ids=[source.id],
        reviewed_by="reviewer-2",
    )
    with pytest.raises(ValueError, match="produces research"):
        lifecycle.resolve(
            contract["id"],
            analysis_id=submitted["id"],
            disposition="adopt",
            rationale="should not resolve research",
            decided_by="reviewer-2",
        )


def test_best_solution_requires_complete_structured_assessment():
    evidence, contracts, lifecycle = setup_services()
    source = capture(evidence, "best-structured")
    contract = best_solution_contract(contracts, source.id)

    with pytest.raises(ValueError, match="requires a selection assessment"):
        lifecycle.submit_analysis(
            contract["id"],
            conclusion="选择官方原始报表",
            confidence=Decimal("0.9"),
            recommended_option_id="official",
            evidence_ids=[source.id],
            submitted_by="analyst-1",
        )

    failed_constraint = best_solution_assessment()
    failed_constraint["hard_constraint_results"][0]["passed"] = False
    with pytest.raises(ValueError, match="must pass every registered hard constraint"):
        lifecycle.submit_analysis(
            contract["id"],
            conclusion="选择官方原始报表",
            confidence=Decimal("0.9"),
            recommended_option_id="official",
            selection_assessment=failed_constraint,
            evidence_ids=[source.id],
            submitted_by="analyst-1",
        )

    incomplete = best_solution_assessment()
    incomplete["option_assessments"] = incomplete["option_assessments"][:-1]
    with pytest.raises(ValueError, match="cover each registered option exactly once"):
        lifecycle.submit_analysis(
            contract["id"],
            conclusion="选择官方原始报表",
            confidence=Decimal("0.9"),
            recommended_option_id="official",
            selection_assessment=incomplete,
            evidence_ids=[source.id],
            submitted_by="analyst-1",
        )

    submitted = lifecycle.submit_analysis(
        contract["id"],
        conclusion="官方原始报表满足硬约束且长期风险最低",
        confidence=Decimal("0.9"),
        recommended_option_id="official",
        selection_assessment=best_solution_assessment(),
        evidence_ids=[source.id],
        submitted_by="analyst-1",
    )
    assert submitted["forecast"] is None
    assert submitted["selection_assessment"]["no_action_option_id"] == "no-action"
    assert len(submitted["selection_assessment"]["rejected_options"]) == 2


def test_best_solution_acceptance_requires_counterargument_before_resolution():
    evidence, contracts, lifecycle = setup_services()
    source = capture(evidence, "best-review")
    contract = best_solution_contract(contracts, source.id)
    submitted = lifecycle.submit_analysis(
        contract["id"],
        conclusion="官方报表是当前最佳来源",
        confidence=Decimal("0.9"),
        recommended_option_id="official",
        selection_assessment=best_solution_assessment(),
        evidence_ids=[source.id],
        submitted_by="analyst-1",
    )

    with pytest.raises(ValueError, match="requires at least one counterargument"):
        lifecycle.review_analysis(
            submitted["id"],
            verdict="accepted",
            rationale="同意结论",
            evidence_ids=[source.id],
            reviewed_by="reviewer-2",
        )

    lifecycle.review_analysis(
        submitted["id"],
        verdict="accepted",
        rationale="官方报表仍需保持人工复核",
        counterarguments=["字段映射错误时，官方来源仍可能被错误解释"],
        evidence_ids=[source.id],
        reviewed_by="reviewer-2",
    )
    resolved = lifecycle.resolve(
        contract["id"],
        analysis_id=submitted["id"],
        disposition="adopt",
        rationale="采纳官方原件作为事实来源，保持人工批准",
        conditions=["禁止自动入账"],
        decided_by="approver-3",
    )
    assert resolved["execution_eligible"] is False


def test_non_best_contract_rejects_selection_assessment():
    evidence, contracts, lifecycle = setup_services()
    source = capture(evidence, "not-best")
    contract = decision_contract(contracts, source.id)

    with pytest.raises(ValueError, match="only valid for a best-solution"):
        lifecycle.submit_analysis(
            contract["id"],
            conclusion="错误附带最佳方案评估",
            confidence=Decimal("0.7"),
            recommended_option_id="A",
            forecast_metric="sample_cm3_cny",
            forecast_value=Decimal("12000"),
            forecast_low=Decimal("5000"),
            forecast_high=Decimal("18000"),
            forecast_unit="CNY",
            forecast_due_at="2026-07-18T00:00:00+00:00",
            selection_assessment=best_solution_assessment(),
            evidence_ids=[source.id],
            submitted_by="analyst-1",
        )

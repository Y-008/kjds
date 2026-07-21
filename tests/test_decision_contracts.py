from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from apps.control_plane.decision_contracts import DecisionContractService
from apps.control_plane.evidence import EvidenceGrade, EvidenceService
from apps.control_plane.sql_repository import Base


def setup_service():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    return evidence, DecisionContractService(engine=engine, evidence=evidence)


def capture(evidence: EvidenceService, ref: str = "decision-source"):
    return evidence.capture(
        content=f"verified source for {ref}".encode(),
        filename=f"{ref}.txt",
        content_type="text/plain",
        source="decision_contract_test",
        source_ref=f"test://{ref}",
        grade=EvidenceGrade.A,
        effective_at="2026-07-17T00:00:00+00:00",
        effective_until=None,
        created_by="tester",
    )


def test_registry_resolves_shortcuts_to_versioned_profiles():
    _, service = setup_service()
    profiles = service.profiles()

    assert len(profiles) == 6
    assert service.resolve_profile("/x10think").id == "decision_review"
    assert service.resolve_profile("/oda").id == "decision_review"
    assert service.resolve_profile("/truth").version == "1.0.0"
    assert service.resolve_profile("/socrates").max_questions == 3
    assert service.resolve_profile("/best").id == "best_solution"


def test_evidence_research_stays_pending_without_verified_evidence():
    _, service = setup_service()
    contract = service.create(
        profile="/truth",
        objective="判断俄罗斯市场需求是否真实增长",
        decision_domain="market_intelligence",
        risk_level="medium",
        requested_by="operator-1",
        unknowns=["平台完整流量尚未获得"],
    )

    assert contract["status"] == "evidence_pending"
    assert contract["execution_eligible"] is False
    assert contract["compiler_policy"]["unknown_policy"] == "UNKNOWN_NOT_GUESS"
    assert contract["evidence_ids"] == []


def test_decision_review_is_idempotent_evidence_linked_and_human_gated():
    evidence, service = setup_service()
    source = capture(evidence)
    values = dict(
        profile="/x10think",
        objective="选择首批样品采购方案",
        decision_domain="procurement",
        risk_level="high",
        maximum_loss_amount=Decimal("30000"),
        currency="CNY",
        options=[
            {"id": "A", "label": "100件小样"},
            {"id": "B", "label": "暂不采购"},
        ],
        evidence_ids=[source.id],
        requested_by="operator-1",
    )

    contract = service.create(**values)
    retry = service.create(**values)

    assert retry["id"] == contract["id"]
    assert contract["status"] == "ready_for_analysis"
    assert contract["requires_human_approval"] is True
    assert contract["execution_eligible"] is False
    assert Decimal(contract["maximum_loss_amount"]) == Decimal("30000")
    assert contract["compiler_policy"]["execution_requires_separate_decision_id"] is True
    assert evidence.target_evidence_ids(
        target_type="decision_contract",
        target_id=contract["id"],
    ) == [source.id]


def test_missing_material_inputs_force_clarification_before_analysis():
    evidence, service = setup_service()
    source = capture(evidence)
    contract = service.create(
        profile="/oda",
        objective="是否扩大广告预算",
        decision_domain="advertising",
        risk_level="critical",
        options=[{"id": "A", "label": "扩大"}],
        evidence_ids=[source.id],
        requested_by="operator-1",
    )

    assert contract["status"] == "clarification_required"
    assert contract["missing_inputs"] == [
        "at_least_two_options",
        "maximum_loss_amount",
    ]
    assert contract["compiler_policy"]["critical_risk_forces_advisory_only"] is True


def test_best_solution_requires_constraints_criteria_and_evidence_before_selection():
    evidence, service = setup_service()
    incomplete = service.create(
        profile="/best",
        objective="选择 Ozon 财务事实来源",
        decision_domain="architecture",
        risk_level="medium",
        options=[
            {"id": "A", "label": "官方原始报表"},
            {"id": "B", "label": "第三方计算器"},
        ],
        requested_by="operator-1",
    )
    assert incomplete["status"] == "clarification_required"
    assert incomplete["missing_inputs"] == [
        "context.hard_constraints",
        "context.decision_criteria",
    ]

    source = capture(evidence, "official-accrual-report")
    ready = service.create(
        profile="best_solution",
        objective="选择 Ozon 财务事实来源",
        decision_domain="architecture",
        risk_level="medium",
        options=[
            {"id": "A", "label": "官方原始报表"},
            {"id": "B", "label": "第三方计算器"},
            {"id": "C", "label": "暂不晋升财务事实"},
        ],
        context={
            "hard_constraints": ["可追溯到 Ozon 一手原件", "不得自动入账"],
            "decision_criteria": [
                "长期风险调整价值",
                "证据质量",
                "总拥有成本",
                "可逆性与回滚",
                "落地时间",
                "运维适配",
            ],
        },
        evidence_ids=[source.id],
        requested_by="operator-1",
    )

    assert ready["status"] == "ready_for_analysis"
    assert ready["compiler_policy"]["selection_rule"] == (
        "HARD_CONSTRAINTS_THEN_RISK_ADJUSTED_LONG_TERM_VALUE"
    )
    assert ready["compiler_policy"]["automatic_equal_weight_score"] is False
    assert ready["compiler_policy"]["latest_or_most_complex_is_not_best"] is True
    assert "rejected_options_and_reasons" in ready["output_requirements"]


def test_contract_rejects_non_finite_maximum_loss():
    _, service = setup_service()

    with pytest.raises(ValueError, match="Maximum loss must be a finite number"):
        service.create(
            profile="/oda",
            objective="验证风险数字边界",
            decision_domain="risk",
            risk_level="high",
            maximum_loss_amount=Decimal("NaN"),
            requested_by="operator-1",
        )


def test_forecast_requires_horizon_baseline_scenarios_and_evidence():
    evidence, service = setup_service()
    pending = service.create(
        profile="/product",
        objective="预测新品未来30天现金贡献",
        decision_domain="forecast",
        risk_level="medium",
        requested_by="operator-1",
    )
    assert pending["missing_inputs"] == [
        "horizon_days",
        "context.baseline",
        "context.scenarios",
    ]

    source = capture(evidence, "forecast-basis")
    ready = service.create(
        profile="probabilistic_forecast",
        objective="预测新品未来30天现金贡献",
        decision_domain="forecast",
        risk_level="medium",
        horizon_days=30,
        context={
            "baseline": {"method": "matched SKU base rate", "value": "0.18"},
            "scenarios": [
                {"name": "base", "probability": "0.6"},
                {"name": "downside", "probability": "0.4"},
            ],
        },
        evidence_ids=[source.id],
        requested_by="operator-1",
    )
    assert ready["status"] == "ready_for_analysis"
    assert "scenario_probability_distribution" in ready["output_requirements"]


def test_plain_language_mode_preserves_source_facts_and_evidence():
    evidence, service = setup_service()
    source = capture(evidence, "source-contract")
    original = service.create(
        profile="/truth",
        objective="解释真实利润口径",
        decision_domain="finance",
        risk_level="low",
        facts={"cm3_cny": "125.40"},
        evidence_ids=[source.id],
        requested_by="reviewer-1",
    )
    explained = service.create(
        profile="/eli10",
        objective="用小白能理解的语言解释上一份结论",
        decision_domain="finance",
        risk_level="low",
        source_contract_id=original["id"],
        requested_by="reviewer-1",
    )

    assert explained["status"] == "ready_for_render"
    assert explained["evidence_ids"] == [source.id]
    assert explained["compiler_policy"]["facts_must_remain_unchanged"] is True


def test_invalid_profile_and_currency_fail_closed():
    _, service = setup_service()
    with pytest.raises(ValueError, match="Unknown interaction profile"):
        service.create(
            profile="/magic",
            objective="test",
            decision_domain="test",
            risk_level="low",
            requested_by="tester",
        )
    with pytest.raises(ValueError, match="three-letter"):
        service.create(
            profile="/truth",
            objective="test",
            decision_domain="test",
            risk_level="low",
            currency="人民币",
            requested_by="tester",
        )

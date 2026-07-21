from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .sql_repository import Base

RiskLevel = Literal["low", "medium", "high", "critical"]


@dataclass(frozen=True, slots=True)
class InteractionProfile:
    id: str
    version: str
    label: str
    description: str
    aliases: tuple[str, ...]
    workflow_steps: tuple[str, ...]
    output_requirements: tuple[str, ...]
    max_questions: int
    presentation_only: bool
    evidence_required_before_conclusion: bool
    requires_options: bool
    requires_forecast_basis: bool

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["aliases"] = list(self.aliases)
        value["workflow_steps"] = list(self.workflow_steps)
        value["output_requirements"] = list(self.output_requirements)
        return value


COMMON_DECISION_OUTPUTS = (
    "conclusion",
    "evidence_with_source_time_grade",
    "assumptions",
    "unknowns",
    "alternatives",
    "downside_and_maximum_loss",
    "stop_conditions",
    "approval_requirement",
    "valid_until",
)

INTERACTION_PROFILES = (
    InteractionProfile(
        id="fast_explain",
        version="1.0.0",
        label="快速解释",
        description="只转换表达层，不改变来源合同中的事实、数字、风险或结论。",
        aliases=("/eli10",),
        workflow_steps=("load_source_contract", "preserve_facts", "render_plain_language"),
        output_requirements=("plain_language_summary", "preserved_unknowns", "source_contract_id"),
        max_questions=0,
        presentation_only=True,
        evidence_required_before_conclusion=False,
        requires_options=False,
        requires_forecast_basis=False,
    ),
    InteractionProfile(
        id="socratic_clarification",
        version="1.0.0",
        label="苏格拉底澄清",
        description="最多提出三个会实质改变方案的问题，随后明确假设和未知项。",
        aliases=("/socrates",),
        workflow_steps=("detect_material_gaps", "ask_up_to_three_questions", "record_assumptions"),
        output_requirements=("material_questions", "clarified_constraints", "remaining_unknowns"),
        max_questions=3,
        presentation_only=False,
        evidence_required_before_conclusion=False,
        requires_options=False,
        requires_forecast_basis=False,
    ),
    InteractionProfile(
        id="evidence_research",
        version="1.0.0",
        label="证据研究",
        description="没有可验证证据时输出 UNKNOWN，不用语言流畅度代替事实。",
        aliases=("/truth",),
        workflow_steps=("separate_fact_assumption", "verify_evidence", "grade_confidence", "state_unknowns"),
        output_requirements=(
            "answer_or_unknown",
            "source_time_and_grade",
            "confidence",
            "conflicting_evidence",
            "invalidation_conditions",
        ),
        max_questions=0,
        presentation_only=False,
        evidence_required_before_conclusion=True,
        requires_options=False,
        requires_forecast_basis=False,
    ),
    InteractionProfile(
        id="decision_review",
        version="1.0.0",
        label="决策评审",
        description="用多方案、反方解释、失败预演和风险预算替代模糊的“深度思考”。",
        aliases=("/x10think", "/oda"),
        workflow_steps=(
            "define_decision",
            "freeze_fact_snapshot",
            "compare_options",
            "red_team",
            "premortem",
            "compile_decision_contract",
        ),
        output_requirements=COMMON_DECISION_OUTPUTS,
        max_questions=0,
        presentation_only=False,
        evidence_required_before_conclusion=True,
        requires_options=True,
        requires_forecast_basis=False,
    ),
    InteractionProfile(
        id="best_solution",
        version="1.0.0",
        label="最佳方案选择",
        description=(
            "先用硬约束淘汰不可行方案，再按证据支撑的长期风险调整价值选择，"
            "不把最新、最复杂或最省代码自动当作最佳。"
        ),
        aliases=("/best",),
        workflow_steps=(
            "define_objective_and_boundaries",
            "freeze_hard_constraints",
            "enumerate_realistic_options",
            "eliminate_infeasible_options",
            "compare_evidence_risk_value_tco_and_reversibility",
            "red_team_preferred_option",
            "record_choice_rejections_and_invalidation_conditions",
        ),
        output_requirements=(
            "chosen_option_id",
            "hard_constraint_results",
            "evidence_quality",
            "expected_risk_adjusted_long_term_value",
            "total_cost_of_ownership",
            "maximum_loss",
            "reversibility_and_rollback",
            "time_to_value",
            "operational_fit",
            "rejected_options_and_reasons",
            "sensitivity_and_invalidation_conditions",
            "approval_requirement",
        ),
        max_questions=0,
        presentation_only=False,
        evidence_required_before_conclusion=True,
        requires_options=True,
        requires_forecast_basis=False,
    ),
    InteractionProfile(
        id="probabilistic_forecast",
        version="1.0.0",
        label="概率预测",
        description="要求基准情景、时间范围、概率区间和未来回填日期，不输出单点神谕。",
        aliases=("/product",),
        workflow_steps=("define_horizon", "record_base_rate", "build_scenarios", "calibrate", "schedule_outcome_review"),
        output_requirements=(
            "baseline",
            "scenario_probability_distribution",
            "confidence_interval",
            "sensitivity_drivers",
            "validation_date",
            "prediction_log_id",
        ),
        max_questions=0,
        presentation_only=False,
        evidence_required_before_conclusion=True,
        requires_options=False,
        requires_forecast_basis=True,
    ),
)

PROFILE_INDEX = {
    key.lower(): profile
    for profile in INTERACTION_PROFILES
    for key in (profile.id, *profile.aliases)
}


class DecisionContractRow(Base):
    __tablename__ = "decision_contracts"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    profile_id: Mapped[str] = mapped_column(String, nullable=False)
    profile_version: Mapped[str] = mapped_column(String, nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    decision_domain: Mapped[str] = mapped_column(String, nullable=False)
    risk_level: Mapped[str] = mapped_column(String, nullable=False)
    horizon_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    maximum_loss_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    source_contract_id: Mapped[str | None] = mapped_column(
        ForeignKey("decision_contracts.id"), nullable=True
    )
    input_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    output_requirements_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    evidence_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    compiler_policy_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    missing_inputs_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    execution_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    requires_human_approval: Mapped[bool] = mapped_column(Boolean, nullable=False)
    requested_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DecisionContractService:
    def __init__(self, *, engine, evidence) -> None:
        self.engine = engine
        self.evidence = evidence

    @staticmethod
    def profiles() -> list[dict[str, Any]]:
        return [profile.to_dict() for profile in INTERACTION_PROFILES]

    @staticmethod
    def resolve_profile(value: str) -> InteractionProfile:
        profile = PROFILE_INDEX.get(value.strip().lower())
        if profile is None:
            raise ValueError(f"Unknown interaction profile or alias: {value}")
        return profile

    def create(
        self,
        *,
        profile: str,
        objective: str,
        decision_domain: str,
        risk_level: RiskLevel,
        requested_by: str,
        horizon_days: int | None = None,
        maximum_loss_amount: Decimal | None = None,
        currency: str = "CNY",
        source_contract_id: str | None = None,
        facts: dict[str, Any] | None = None,
        assumptions: list[str] | None = None,
        unknowns: list[str] | None = None,
        options: list[dict[str, Any]] | None = None,
        evidence_ids: list[str] | None = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        selected = self.resolve_profile(profile)
        objective = objective.strip()
        decision_domain = decision_domain.strip().lower()
        currency = currency.strip().upper()
        if not objective or not decision_domain:
            raise ValueError("Decision contract requires an objective and decision domain")
        if risk_level not in {"low", "medium", "high", "critical"}:
            raise ValueError("Risk level must be low, medium, high, or critical")
        if len(currency) != 3 or not all("A" <= char <= "Z" for char in currency):
            raise ValueError("Currency must be a three-letter code")
        if horizon_days is not None and not 1 <= horizon_days <= 3650:
            raise ValueError("Horizon days must be between 1 and 3650")
        if maximum_loss_amount is not None:
            try:
                maximum_loss_amount = Decimal(maximum_loss_amount)
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise ValueError("Maximum loss must be a finite number") from exc
            if not maximum_loss_amount.is_finite():
                raise ValueError("Maximum loss must be a finite number")
            if maximum_loss_amount < 0:
                raise ValueError("Maximum loss cannot be negative")

        normalized_evidence = sorted({item.strip() for item in evidence_ids or [] if item.strip()})
        if normalized_evidence:
            self.evidence.require_valid(normalized_evidence)
        source = self.get(source_contract_id) if source_contract_id else None
        if selected.presentation_only and source is not None and not normalized_evidence:
            normalized_evidence = list(source["evidence_ids"])

        payload = {
            "facts": facts or {},
            "assumptions": self._clean_strings(assumptions),
            "unknowns": self._clean_strings(unknowns),
            "options": options or [],
            "context": context or {},
        }
        missing = self._missing_inputs(
            selected,
            risk_level=risk_level,
            horizon_days=horizon_days,
            maximum_loss_amount=maximum_loss_amount,
            source_contract_id=source_contract_id,
            payload=payload,
        )
        status = self._status(selected, missing, normalized_evidence)
        requires_human_approval = risk_level in {"high", "critical"}
        compiler_policy = {
            "unknown_policy": "UNKNOWN_NOT_GUESS",
            "facts_must_remain_unchanged": selected.presentation_only,
            "max_material_questions": selected.max_questions,
            "evidence_required_before_conclusion": selected.evidence_required_before_conclusion,
            "model_may_execute": False,
            "execution_requires_separate_decision_id": True,
            "mandatory_human_approval": requires_human_approval,
            "critical_risk_forces_advisory_only": risk_level == "critical",
        }
        if selected.id == "best_solution":
            compiler_policy.update(
                {
                    "selection_rule": "HARD_CONSTRAINTS_THEN_RISK_ADJUSTED_LONG_TERM_VALUE",
                    "automatic_equal_weight_score": False,
                    "latest_or_most_complex_is_not_best": True,
                    "must_include_no_action_when_feasible": True,
                    "must_record_rejected_options": True,
                    "must_state_invalidation_conditions": True,
                }
            )
        canonical = {
            "profile_id": selected.id,
            "profile_version": selected.version,
            "objective": objective,
            "decision_domain": decision_domain,
            "risk_level": risk_level,
            "horizon_days": horizon_days,
            "maximum_loss_amount": (
                str(maximum_loss_amount) if maximum_loss_amount is not None else None
            ),
            "currency": currency,
            "source_contract_id": source_contract_id,
            "input": payload,
            "evidence_ids": normalized_evidence,
            "requested_by": requested_by,
        }
        request_hash = hashlib.sha256(
            json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        now = datetime.now(UTC)
        with Session(self.engine) as session, session.begin():
            existing = session.scalar(
                select(DecisionContractRow).where(DecisionContractRow.request_hash == request_hash)
            )
            if existing is not None:
                return self._view(existing)
            row = DecisionContractRow(
                id=new_id("dcn"),
                request_hash=request_hash,
                profile_id=selected.id,
                profile_version=selected.version,
                objective=objective,
                decision_domain=decision_domain,
                risk_level=risk_level,
                horizon_days=horizon_days,
                maximum_loss_amount=maximum_loss_amount,
                currency=currency,
                source_contract_id=source_contract_id,
                input_json=payload,
                output_requirements_json=list(selected.output_requirements),
                evidence_json=normalized_evidence,
                compiler_policy_json=compiler_policy,
                missing_inputs_json=missing,
                status=status,
                execution_eligible=False,
                requires_human_approval=requires_human_approval,
                requested_by=requested_by,
                created_at=now,
            )
            session.add(row)
            session.flush()
            result = self._view(row)
        for evidence_id in normalized_evidence:
            self.evidence.link(
                evidence_id=evidence_id,
                target_type="decision_contract",
                target_id=result["id"],
                relationship="supports_input",
                created_by=requested_by,
            )
        return result

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            rows = list(
                session.scalars(
                    select(DecisionContractRow)
                    .order_by(DecisionContractRow.created_at.desc(), DecisionContractRow.id)
                    .limit(min(max(limit, 1), 500))
                )
            )
        return [self._view(row) for row in rows]

    def get(self, contract_id: str | None) -> dict[str, Any]:
        if not contract_id:
            raise KeyError("Decision contract id is required")
        with Session(self.engine) as session:
            row = session.get(DecisionContractRow, contract_id)
            if row is None:
                raise KeyError(f"Unknown decision contract: {contract_id}")
            return self._view(row)

    @staticmethod
    def _clean_strings(values: list[str] | None) -> list[str]:
        return [item.strip() for item in values or [] if item.strip()]

    @staticmethod
    def _missing_inputs(
        profile: InteractionProfile,
        *,
        risk_level: str,
        horizon_days: int | None,
        maximum_loss_amount: Decimal | None,
        source_contract_id: str | None,
        payload: dict[str, Any],
    ) -> list[str]:
        missing = []
        if profile.presentation_only and not source_contract_id:
            missing.append("source_contract_id")
        if profile.requires_options and len(payload["options"]) < 2:
            missing.append("at_least_two_options")
        if profile.id == "best_solution":
            options = payload["options"]
            if any(
                not isinstance(option, dict)
                or not str(option.get("id", "")).strip()
                or not str(option.get("label", "")).strip()
                for option in options
            ):
                missing.append("options_with_id_and_label")
            hard_constraints = payload["context"].get("hard_constraints")
            if not isinstance(hard_constraints, list) or not any(
                str(item).strip() for item in hard_constraints
            ):
                missing.append("context.hard_constraints")
            decision_criteria = payload["context"].get("decision_criteria")
            if not isinstance(decision_criteria, list) or not any(
                str(item).strip() for item in decision_criteria
            ):
                missing.append("context.decision_criteria")
        if risk_level in {"high", "critical"} and maximum_loss_amount is None:
            missing.append("maximum_loss_amount")
        if profile.requires_forecast_basis:
            if horizon_days is None:
                missing.append("horizon_days")
            if not payload["context"].get("baseline"):
                missing.append("context.baseline")
            scenarios = payload["context"].get("scenarios")
            if not isinstance(scenarios, list) or len(scenarios) < 2:
                missing.append("context.scenarios")
        return missing

    @staticmethod
    def _status(
        profile: InteractionProfile, missing: list[str], evidence_ids: list[str]
    ) -> str:
        if missing:
            return "clarification_required"
        if profile.id == "socratic_clarification":
            return "ready_for_clarification"
        if profile.evidence_required_before_conclusion and not evidence_ids:
            return "evidence_pending"
        if profile.presentation_only:
            return "ready_for_render"
        return "ready_for_analysis"

    @staticmethod
    def _view(row: DecisionContractRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "request_hash": row.request_hash,
            "profile_id": row.profile_id,
            "profile_version": row.profile_version,
            "objective": row.objective,
            "decision_domain": row.decision_domain,
            "risk_level": row.risk_level,
            "horizon_days": row.horizon_days,
            "maximum_loss_amount": (
                str(row.maximum_loss_amount) if row.maximum_loss_amount is not None else None
            ),
            "currency": row.currency,
            "source_contract_id": row.source_contract_id,
            "input": row.input_json,
            "output_requirements": row.output_requirements_json,
            "evidence_ids": row.evidence_json,
            "compiler_policy": row.compiler_policy_json,
            "missing_inputs": row.missing_inputs_json,
            "status": row.status,
            "execution_eligible": row.execution_eligible,
            "requires_human_approval": row.requires_human_approval,
            "requested_by": row.requested_by,
            "created_at": row.created_at.isoformat(),
        }

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .sql_repository import Base

ReviewVerdict = Literal["accepted", "needs_revision", "rejected"]
DecisionDisposition = Literal["adopt", "experiment", "defer", "reject"]


class DecisionAnalysisRow(Base):
    __tablename__ = "decision_analyses"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    contract_id: Mapped[str] = mapped_column(
        ForeignKey("decision_contracts.id"), nullable=False
    )
    conclusion: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_option_id: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence_decimal: Mapped[Decimal] = mapped_column(Numeric(8, 7), nullable=False)
    forecast_metric: Mapped[str | None] = mapped_column(String, nullable=True)
    forecast_value_decimal: Mapped[Decimal | None] = mapped_column(
        Numeric(38, 12), nullable=True
    )
    forecast_low_decimal: Mapped[Decimal | None] = mapped_column(
        Numeric(38, 12), nullable=True
    )
    forecast_high_decimal: Mapped[Decimal | None] = mapped_column(
        Numeric(38, 12), nullable=True
    )
    forecast_unit: Mapped[str | None] = mapped_column(String, nullable=True)
    forecast_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    assumptions_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    unknowns_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    evidence_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    model_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    submitted_by: Mapped[str] = mapped_column(String, nullable=False)
    execution_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DecisionAnalysisReviewRow(Base):
    __tablename__ = "decision_analysis_reviews"
    __table_args__ = (
        UniqueConstraint(
            "analysis_id",
            "reviewed_by",
            name="uq_decision_analysis_reviewer",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("decision_analyses.id"), nullable=False
    )
    verdict: Mapped[str] = mapped_column(String, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    counterarguments_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    evidence_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    reviewed_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DecisionResolutionRow(Base):
    __tablename__ = "decision_resolutions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    contract_id: Mapped[str] = mapped_column(
        ForeignKey("decision_contracts.id"), unique=True, nullable=False
    )
    analysis_id: Mapped[str] = mapped_column(
        ForeignKey("decision_analyses.id"), nullable=False
    )
    disposition: Mapped[str] = mapped_column(String, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    conditions_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    decided_by: Mapped[str] = mapped_column(String, nullable=False)
    execution_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DecisionOutcomeRow(Base):
    __tablename__ = "decision_outcomes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    resolution_id: Mapped[str] = mapped_column(
        ForeignKey("decision_resolutions.id"), unique=True, nullable=False
    )
    metric: Mapped[str] = mapped_column(String, nullable=False)
    predicted_value_decimal: Mapped[Decimal] = mapped_column(
        Numeric(38, 12), nullable=False
    )
    interval_low_decimal: Mapped[Decimal] = mapped_column(
        Numeric(38, 12), nullable=False
    )
    interval_high_decimal: Mapped[Decimal] = mapped_column(
        Numeric(38, 12), nullable=False
    )
    actual_value_decimal: Mapped[Decimal] = mapped_column(
        Numeric(38, 12), nullable=False
    )
    unit: Mapped[str] = mapped_column(String, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False)
    recorded_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DecisionLifecycleService:
    def __init__(self, *, engine, contracts, evidence) -> None:
        self.engine = engine
        self.contracts = contracts
        self.evidence = evidence

    def submit_analysis(
        self,
        contract_id: str,
        *,
        conclusion: str,
        confidence: Decimal,
        submitted_by: str,
        evidence_ids: list[str],
        recommended_option_id: str | None = None,
        forecast_metric: str | None = None,
        forecast_value: Decimal | None = None,
        forecast_low: Decimal | None = None,
        forecast_high: Decimal | None = None,
        forecast_unit: str | None = None,
        forecast_due_at: str | None = None,
        assumptions: list[str] | None = None,
        unknowns: list[str] | None = None,
        model_ref: str | None = None,
    ) -> dict[str, Any]:
        contract = self.contracts.get(contract_id)
        if contract["status"] != "ready_for_analysis":
            raise ValueError(
                f"Decision contract is not analysis-ready: {contract['status']}"
            )
        conclusion = conclusion.strip()
        submitted_by = submitted_by.strip()
        if not conclusion or not submitted_by:
            raise ValueError("Analysis requires a conclusion and submitting identity")
        confidence = Decimal(confidence)
        if not Decimal("0") <= confidence <= Decimal("1"):
            raise ValueError("Analysis confidence must be between 0 and 1")
        evidence_ids = self._evidence(evidence_ids)

        options = contract["input"].get("options") or []
        option_ids = {
            str(item.get("id"))
            for item in options
            if isinstance(item, dict) and item.get("id") is not None
        }
        recommended_option_id = (
            recommended_option_id.strip() if recommended_option_id else None
        )
        if contract["profile_id"] == "decision_review":
            if not recommended_option_id or recommended_option_id not in option_ids:
                raise ValueError("Decision review analysis must select a registered option id")
        elif recommended_option_id:
            raise ValueError("Recommended option is only valid for a decision review contract")

        forecast = self._forecast(
            required=contract["profile_id"] in {"decision_review", "probabilistic_forecast"},
            metric=forecast_metric,
            value=forecast_value,
            low=forecast_low,
            high=forecast_high,
            unit=forecast_unit,
            due_at=forecast_due_at,
        )
        clean_assumptions = self._strings(assumptions)
        clean_unknowns = self._strings(unknowns)
        canonical = {
            "contract_id": contract_id,
            "conclusion": conclusion,
            "recommended_option_id": recommended_option_id,
            "confidence": str(confidence),
            "forecast": forecast,
            "assumptions": clean_assumptions,
            "unknowns": clean_unknowns,
            "evidence_ids": evidence_ids,
            "model_ref": model_ref.strip() if model_ref else None,
            "submitted_by": submitted_by,
        }
        request_hash = self._hash(canonical)
        with Session(self.engine) as session, session.begin():
            existing = session.scalar(
                select(DecisionAnalysisRow).where(
                    DecisionAnalysisRow.request_hash == request_hash
                )
            )
            if existing is not None:
                return self._analysis(existing)
            resolution = session.scalar(
                select(DecisionResolutionRow.id).where(
                    DecisionResolutionRow.contract_id == contract_id
                )
            )
            if resolution is not None:
                raise ValueError("Resolved decision contract cannot accept a new analysis")
            row = DecisionAnalysisRow(
                id=new_id("dan"),
                request_hash=request_hash,
                contract_id=contract_id,
                conclusion=conclusion,
                recommended_option_id=recommended_option_id,
                confidence_decimal=confidence,
                forecast_metric=forecast["metric"],
                forecast_value_decimal=forecast["value"],
                forecast_low_decimal=forecast["low"],
                forecast_high_decimal=forecast["high"],
                forecast_unit=forecast["unit"],
                forecast_due_at=forecast["due_at"],
                assumptions_json=clean_assumptions,
                unknowns_json=clean_unknowns,
                evidence_json=evidence_ids,
                model_ref=model_ref.strip() if model_ref else None,
                submitted_by=submitted_by,
                execution_eligible=False,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            result = self._analysis(row)
        self._link(evidence_ids, "decision_analysis", result["id"], submitted_by)
        return result

    def review_analysis(
        self,
        analysis_id: str,
        *,
        verdict: ReviewVerdict,
        rationale: str,
        reviewed_by: str,
        counterarguments: list[str] | None = None,
        evidence_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        analysis = self.get_analysis(analysis_id)
        reviewed_by = reviewed_by.strip()
        rationale = rationale.strip()
        if verdict not in {"accepted", "needs_revision", "rejected"}:
            raise ValueError("Review verdict must be accepted, needs_revision, or rejected")
        if not reviewed_by or not rationale:
            raise ValueError("Review requires an identity and rationale")
        if reviewed_by == analysis["submitted_by"]:
            raise ValueError("Analysis submitter cannot independently review their own work")
        evidence_ids = self._evidence(evidence_ids or [], required=verdict == "accepted")
        counterarguments = self._strings(counterarguments)
        canonical = {
            "analysis_id": analysis_id,
            "verdict": verdict,
            "rationale": rationale,
            "counterarguments": counterarguments,
            "evidence_ids": evidence_ids,
            "reviewed_by": reviewed_by,
        }
        request_hash = self._hash(canonical)
        with Session(self.engine) as session, session.begin():
            exact = session.scalar(
                select(DecisionAnalysisReviewRow).where(
                    DecisionAnalysisReviewRow.request_hash == request_hash
                )
            )
            if exact is not None:
                return self._review(exact)
            resolution = session.scalar(
                select(DecisionResolutionRow.id).where(
                    DecisionResolutionRow.analysis_id == analysis_id
                )
            )
            if resolution is not None:
                raise ValueError("Resolved analysis cannot accept a new review")
            previous = session.scalar(
                select(DecisionAnalysisReviewRow).where(
                    DecisionAnalysisReviewRow.analysis_id == analysis_id,
                    DecisionAnalysisReviewRow.reviewed_by == reviewed_by,
                )
            )
            if previous is not None:
                raise ValueError("Reviewer has already submitted an immutable review")
            row = DecisionAnalysisReviewRow(
                id=new_id("drv"),
                request_hash=request_hash,
                analysis_id=analysis_id,
                verdict=verdict,
                rationale=rationale,
                counterarguments_json=counterarguments,
                evidence_json=evidence_ids,
                reviewed_by=reviewed_by,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            result = self._review(row)
        self._link(evidence_ids, "decision_analysis_review", result["id"], reviewed_by)
        return result

    def resolve(
        self,
        contract_id: str,
        *,
        analysis_id: str,
        disposition: DecisionDisposition,
        rationale: str,
        decided_by: str,
        conditions: list[str] | None = None,
    ) -> dict[str, Any]:
        contract = self.contracts.get(contract_id)
        analysis = self.get_analysis(analysis_id)
        if contract["profile_id"] not in {
            "decision_review",
            "probabilistic_forecast",
        }:
            raise ValueError("This interaction mode produces research, not a formal resolution")
        if analysis["contract_id"] != contract_id:
            raise ValueError("Analysis does not belong to the decision contract")
        if disposition not in {"adopt", "experiment", "defer", "reject"}:
            raise ValueError("Unknown decision disposition")
        rationale = rationale.strip()
        decided_by = decided_by.strip()
        if not rationale or not decided_by:
            raise ValueError("Resolution requires a rationale and deciding identity")
        if decided_by == analysis["submitted_by"]:
            raise ValueError("Analysis submitter cannot make the formal decision")
        reviews = self.list_reviews(analysis_id)
        blocking = [item for item in reviews if item["verdict"] != "accepted"]
        required_reviews = 2 if contract["risk_level"] == "critical" else 1
        accepted = [item for item in reviews if item["verdict"] == "accepted"]
        if blocking:
            raise ValueError("Analysis has a blocking independent review")
        if len(accepted) < required_reviews:
            raise ValueError(
                f"Resolution requires {required_reviews} accepted independent review(s)"
            )
        if contract["risk_level"] == "critical" and decided_by in {
            item["reviewed_by"] for item in accepted
        }:
            raise ValueError("Critical decision maker must be independent from reviewers")
        conditions = self._strings(conditions)
        canonical = {
            "contract_id": contract_id,
            "analysis_id": analysis_id,
            "disposition": disposition,
            "rationale": rationale,
            "conditions": conditions,
            "decided_by": decided_by,
        }
        request_hash = self._hash(canonical)
        with Session(self.engine) as session, session.begin():
            exact = session.scalar(
                select(DecisionResolutionRow).where(
                    DecisionResolutionRow.request_hash == request_hash
                )
            )
            if exact is not None:
                return self._resolution(exact)
            previous = session.scalar(
                select(DecisionResolutionRow).where(
                    DecisionResolutionRow.contract_id == contract_id
                )
            )
            if previous is not None:
                raise ValueError(
                    "Decision contract is already resolved; create a new contract to revise it"
                )
            row = DecisionResolutionRow(
                id=new_id("dec"),
                request_hash=request_hash,
                contract_id=contract_id,
                analysis_id=analysis_id,
                disposition=disposition,
                rationale=rationale,
                conditions_json=conditions,
                decided_by=decided_by,
                execution_eligible=False,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            return self._resolution(row)

    def record_outcome(
        self,
        resolution_id: str,
        *,
        actual_value: Decimal,
        observed_at: str,
        evidence_ids: list[str],
        notes: str,
        recorded_by: str,
    ) -> dict[str, Any]:
        resolution = self.get_resolution(resolution_id)
        if resolution["disposition"] not in {"adopt", "experiment"}:
            raise ValueError("Only adopted or experimental decisions can record outcomes")
        analysis = self.get_analysis(resolution["analysis_id"])
        forecast = analysis["forecast"]
        if forecast is None:
            raise ValueError("Decision analysis has no registered forecast to evaluate")
        observed = self._datetime(observed_at, "observed_at")
        due_at = self._datetime(forecast["due_at"], "forecast_due_at")
        if observed < due_at:
            raise ValueError("Outcome cannot be recorded before the registered forecast due date")
        actual = Decimal(actual_value)
        evidence_ids = self._evidence(evidence_ids)
        notes = notes.strip()
        recorded_by = recorded_by.strip()
        if not notes or not recorded_by:
            raise ValueError("Outcome requires notes and a recording identity")
        canonical = {
            "resolution_id": resolution_id,
            "actual_value": str(actual),
            "observed_at": observed.isoformat(),
            "evidence_ids": evidence_ids,
            "notes": notes,
            "recorded_by": recorded_by,
        }
        request_hash = self._hash(canonical)
        with Session(self.engine) as session, session.begin():
            exact = session.scalar(
                select(DecisionOutcomeRow).where(
                    DecisionOutcomeRow.request_hash == request_hash
                )
            )
            if exact is not None:
                return self._outcome(exact)
            previous = session.scalar(
                select(DecisionOutcomeRow).where(
                    DecisionOutcomeRow.resolution_id == resolution_id
                )
            )
            if previous is not None:
                raise ValueError("Decision outcome is immutable and has already been recorded")
            row = DecisionOutcomeRow(
                id=new_id("out"),
                request_hash=request_hash,
                resolution_id=resolution_id,
                metric=forecast["metric"],
                predicted_value_decimal=Decimal(forecast["value"]),
                interval_low_decimal=Decimal(forecast["low"]),
                interval_high_decimal=Decimal(forecast["high"]),
                actual_value_decimal=actual,
                unit=forecast["unit"],
                observed_at=observed,
                evidence_json=evidence_ids,
                notes=notes,
                recorded_by=recorded_by,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            result = self._outcome(row)
        self._link(evidence_ids, "decision_outcome", result["id"], recorded_by)
        return result

    def list_analyses(self, contract_id: str | None = None) -> list[dict[str, Any]]:
        query = select(DecisionAnalysisRow)
        if contract_id:
            query = query.where(DecisionAnalysisRow.contract_id == contract_id)
        with Session(self.engine) as session:
            rows = list(
                session.scalars(
                    query.order_by(
                        DecisionAnalysisRow.created_at.desc(),
                        DecisionAnalysisRow.id,
                    )
                )
            )
        return [self._analysis(row) for row in rows]

    def get_analysis(self, analysis_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            row = session.get(DecisionAnalysisRow, analysis_id)
            if row is None:
                raise KeyError(f"Unknown decision analysis: {analysis_id}")
            return self._analysis(row)

    def list_reviews(self, analysis_id: str) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            rows = list(
                session.scalars(
                    select(DecisionAnalysisReviewRow)
                    .where(DecisionAnalysisReviewRow.analysis_id == analysis_id)
                    .order_by(
                        DecisionAnalysisReviewRow.created_at,
                        DecisionAnalysisReviewRow.id,
                    )
                )
            )
        return [self._review(row) for row in rows]

    def list_resolutions(self) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            rows = list(
                session.scalars(
                    select(DecisionResolutionRow).order_by(
                        DecisionResolutionRow.created_at.desc(),
                        DecisionResolutionRow.id,
                    )
                )
            )
        return [self._resolution(row) for row in rows]

    def get_resolution(self, resolution_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            row = session.get(DecisionResolutionRow, resolution_id)
            if row is None:
                raise KeyError(f"Unknown decision resolution: {resolution_id}")
            return self._resolution(row)

    def list_outcomes(self) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            rows = list(
                session.scalars(
                    select(DecisionOutcomeRow).order_by(
                        DecisionOutcomeRow.observed_at.desc(),
                        DecisionOutcomeRow.id,
                    )
                )
            )
        return [self._outcome(row) for row in rows]

    def calibration(self) -> list[dict[str, Any]]:
        outcomes = self.list_outcomes()
        groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for outcome in outcomes:
            groups.setdefault((outcome["metric"], outcome["unit"]), []).append(outcome)
        result = []
        for (metric, unit), items in sorted(groups.items()):
            absolute_errors = [Decimal(item["absolute_error"]) for item in items]
            percentage_errors = [
                Decimal(item["absolute_percentage_error"])
                for item in items
                if item["absolute_percentage_error"] is not None
            ]
            covered = sum(1 for item in items if item["interval_covered"])
            result.append(
                {
                    "metric": metric,
                    "unit": unit,
                    "outcome_count": len(items),
                    "mean_absolute_error": str(
                        sum(absolute_errors, Decimal("0")) / len(absolute_errors)
                    ),
                    "mean_absolute_percentage_error": (
                        str(sum(percentage_errors, Decimal("0")) / len(percentage_errors))
                        if percentage_errors
                        else None
                    ),
                    "interval_coverage": str(Decimal(covered) / Decimal(len(items))),
                }
            )
        return result

    @staticmethod
    def _hash(value: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode()
        ).hexdigest()

    def _evidence(self, values: list[str], *, required: bool = True) -> list[str]:
        normalized = sorted({item.strip() for item in values if item.strip()})
        if required and not normalized:
            raise ValueError("At least one immutable evidence record is required")
        if normalized:
            self.evidence.require_valid(normalized)
        return normalized

    @staticmethod
    def _strings(values: list[str] | None) -> list[str]:
        return [item.strip() for item in values or [] if item.strip()]

    @classmethod
    def _forecast(
        cls,
        *,
        required: bool,
        metric: str | None,
        value: Decimal | None,
        low: Decimal | None,
        high: Decimal | None,
        unit: str | None,
        due_at: str | None,
    ) -> dict[str, Any]:
        supplied = [metric, value, low, high, unit, due_at]
        if not required and not any(item is not None for item in supplied):
            return {"metric": None, "value": None, "low": None, "high": None, "unit": None, "due_at": None}
        if any(item is None for item in supplied):
            raise ValueError("Forecast requires metric, value, interval, unit, and due date")
        metric = str(metric).strip()
        unit = str(unit).strip().upper()
        if not metric or not unit:
            raise ValueError("Forecast metric and unit cannot be blank")
        value = Decimal(value)
        low = Decimal(low)
        high = Decimal(high)
        if low > value or value > high:
            raise ValueError("Forecast value must be inside its low/high interval")
        due = cls._datetime(str(due_at), "forecast_due_at")
        return {
            "metric": metric,
            "value": value,
            "low": low,
            "high": high,
            "unit": unit,
            "due_at": due,
        }

    @staticmethod
    def _datetime(value: str, name: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{name} must be an ISO-8601 datetime") from exc
        if parsed.tzinfo is None:
            raise ValueError(f"{name} must include a timezone")
        return parsed.astimezone(UTC)

    def _link(self, evidence_ids: list[str], target_type: str, target_id: str, actor: str) -> None:
        for evidence_id in evidence_ids:
            self.evidence.link(
                evidence_id=evidence_id,
                target_type=target_type,
                target_id=target_id,
                relationship="supports",
                created_by=actor,
            )

    @staticmethod
    def _analysis(row: DecisionAnalysisRow) -> dict[str, Any]:
        forecast = None
        if row.forecast_metric is not None:
            forecast = {
                "metric": row.forecast_metric,
                "value": str(row.forecast_value_decimal),
                "low": str(row.forecast_low_decimal),
                "high": str(row.forecast_high_decimal),
                "unit": row.forecast_unit,
                "due_at": DecisionLifecycleService._iso_utc(row.forecast_due_at),
            }
        return {
            "id": row.id,
            "contract_id": row.contract_id,
            "conclusion": row.conclusion,
            "recommended_option_id": row.recommended_option_id,
            "confidence": str(row.confidence_decimal),
            "forecast": forecast,
            "assumptions": row.assumptions_json,
            "unknowns": row.unknowns_json,
            "evidence_ids": row.evidence_json,
            "model_ref": row.model_ref,
            "submitted_by": row.submitted_by,
            "execution_eligible": row.execution_eligible,
            "created_at": row.created_at.isoformat(),
        }

    @staticmethod
    def _review(row: DecisionAnalysisReviewRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "analysis_id": row.analysis_id,
            "verdict": row.verdict,
            "rationale": row.rationale,
            "counterarguments": row.counterarguments_json,
            "evidence_ids": row.evidence_json,
            "reviewed_by": row.reviewed_by,
            "created_at": row.created_at.isoformat(),
        }

    @staticmethod
    def _resolution(row: DecisionResolutionRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "contract_id": row.contract_id,
            "analysis_id": row.analysis_id,
            "disposition": row.disposition,
            "rationale": row.rationale,
            "conditions": row.conditions_json,
            "decided_by": row.decided_by,
            "execution_eligible": row.execution_eligible,
            "created_at": row.created_at.isoformat(),
        }

    @staticmethod
    def _outcome(row: DecisionOutcomeRow) -> dict[str, Any]:
        predicted = Decimal(row.predicted_value_decimal)
        actual = Decimal(row.actual_value_decimal)
        signed_error = actual - predicted
        absolute_error = abs(signed_error)
        return {
            "id": row.id,
            "resolution_id": row.resolution_id,
            "metric": row.metric,
            "predicted_value": str(predicted),
            "interval_low": str(row.interval_low_decimal),
            "interval_high": str(row.interval_high_decimal),
            "actual_value": str(actual),
            "unit": row.unit,
            "signed_error": str(signed_error),
            "absolute_error": str(absolute_error),
            "absolute_percentage_error": (
                str(absolute_error / abs(predicted)) if predicted != 0 else None
            ),
            "interval_covered": (
                Decimal(row.interval_low_decimal)
                <= actual
                <= Decimal(row.interval_high_decimal)
            ),
            "observed_at": DecisionLifecycleService._iso_utc(row.observed_at),
            "evidence_ids": row.evidence_json,
            "notes": row.notes,
            "recorded_by": row.recorded_by,
            "created_at": row.created_at.isoformat(),
        }

    @staticmethod
    def _iso_utc(value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat()

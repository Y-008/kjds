from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .sql_repository import Base

ExperimentReviewVerdict = Literal["accepted", "needs_replication", "rejected"]


class CausalExperimentReviewRow(Base):
    __tablename__ = "causal_experiment_reviews"
    __table_args__ = (
        UniqueConstraint(
            "protocol_id",
            "reviewed_by",
            name="uq_causal_experiment_reviewer",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    protocol_id: Mapped[str] = mapped_column(
        ForeignKey("causal_experiment_protocols.id"), nullable=False
    )
    evaluation_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluation_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    verdict: Mapped[str] = mapped_column(String, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    method_assessment: Mapped[str] = mapped_column(Text, nullable=False)
    data_quality_assessment: Mapped[str] = mapped_column(Text, nullable=False)
    counterarguments_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    evidence_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    reviewed_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CausalKnowledgeEntryRow(Base):
    __tablename__ = "causal_knowledge_entries"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    protocol_id: Mapped[str] = mapped_column(
        ForeignKey("causal_experiment_protocols.id"), unique=True, nullable=False
    )
    review_id: Mapped[str] = mapped_column(
        ForeignKey("causal_experiment_reviews.id"), unique=True, nullable=False
    )
    claim: Mapped[str] = mapped_column(Text, nullable=False)
    mechanism: Mapped[str] = mapped_column(Text, nullable=False)
    applicability_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    falsification_conditions_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    effect_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    evidence_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reevaluate_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    execution_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CausalReplicationLinkRow(Base):
    __tablename__ = "causal_replication_links"
    __table_args__ = (
        UniqueConstraint(
            "source_knowledge_id",
            "replication_knowledge_id",
            name="uq_causal_replication_pair",
        ),
        UniqueConstraint(
            "replication_knowledge_id",
            name="uq_causal_replication_child",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    source_knowledge_id: Mapped[str] = mapped_column(
        ForeignKey("causal_knowledge_entries.id"), nullable=False
    )
    replication_knowledge_id: Mapped[str] = mapped_column(
        ForeignKey("causal_knowledge_entries.id"), nullable=False
    )
    scope_relation: Mapped[str] = mapped_column(String, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CausalKnowledgeService:
    def __init__(self, *, engine, experiments, evidence) -> None:
        self.engine = engine
        self.experiments = experiments
        self.evidence = evidence

    def review_experiment(
        self,
        protocol_id: str,
        *,
        verdict: ExperimentReviewVerdict,
        rationale: str,
        method_assessment: str,
        data_quality_assessment: str,
        counterarguments: list[str],
        evidence_ids: list[str],
        reviewed_by: str,
    ) -> dict[str, Any]:
        protocol = self.experiments.get(protocol_id)
        evaluation = self.experiments.evaluate(protocol_id)
        if not evaluation["review_eligible"]:
            raise ValueError("Experiment is not eligible for independent review")
        reviewed_by = reviewed_by.strip()
        if not reviewed_by or reviewed_by == protocol["created_by"]:
            raise ValueError("Experiment owner cannot independently review their own work")
        if verdict not in {"accepted", "needs_replication", "rejected"}:
            raise ValueError("Invalid causal experiment review verdict")
        rationale = self._required(rationale, "Review rationale")
        method_assessment = self._required(method_assessment, "Method assessment")
        data_quality_assessment = self._required(
            data_quality_assessment, "Data quality assessment"
        )
        counterarguments = self._strings(counterarguments)
        if not counterarguments:
            raise ValueError("Independent review requires at least one counterargument")
        evidence_ids = self._evidence(evidence_ids)
        evaluation_hash = self._hash(evaluation)
        canonical = {
            "protocol_id": protocol_id,
            "evaluation_hash": evaluation_hash,
            "verdict": verdict,
            "rationale": rationale,
            "method_assessment": method_assessment,
            "data_quality_assessment": data_quality_assessment,
            "counterarguments": counterarguments,
            "evidence_ids": evidence_ids,
            "reviewed_by": reviewed_by,
        }
        request_hash = self._hash(canonical)
        with Session(self.engine) as session, session.begin():
            exact = session.scalar(
                select(CausalExperimentReviewRow).where(
                    CausalExperimentReviewRow.request_hash == request_hash
                )
            )
            if exact is not None:
                return self._review(exact)
            previous = session.scalar(
                select(CausalExperimentReviewRow).where(
                    CausalExperimentReviewRow.protocol_id == protocol_id,
                    CausalExperimentReviewRow.reviewed_by == reviewed_by,
                )
            )
            if previous is not None:
                raise ValueError("Reviewer has already submitted an immutable review")
            row = CausalExperimentReviewRow(
                id=new_id("cer"),
                request_hash=request_hash,
                protocol_id=protocol_id,
                evaluation_hash=evaluation_hash,
                evaluation_json=evaluation,
                verdict=verdict,
                rationale=rationale,
                method_assessment=method_assessment,
                data_quality_assessment=data_quality_assessment,
                counterarguments_json=counterarguments,
                evidence_json=evidence_ids,
                reviewed_by=reviewed_by,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            result = self._review(row)
        self._link(evidence_ids, "causal_experiment_review", result["id"], reviewed_by)
        return result

    def publish(
        self,
        protocol_id: str,
        *,
        review_id: str,
        claim: str,
        mechanism: str,
        applicability: dict[str, Any],
        falsification_conditions: list[str],
        evidence_ids: list[str],
        valid_from: str,
        reevaluate_at: str,
        created_by: str,
        replicates_knowledge_id: str | None = None,
        replication_rationale: str | None = None,
    ) -> dict[str, Any]:
        protocol = self.experiments.get(protocol_id)
        evaluation = self.experiments.evaluate(protocol_id)
        if not evaluation["review_eligible"]:
            raise ValueError("Only a currently valid experiment can become causal knowledge")
        review = self.get_review(review_id)
        if review["protocol_id"] != protocol_id or review["verdict"] != "accepted":
            raise ValueError("Knowledge publication requires an accepted review for this experiment")
        if review["evaluation_hash"] != self._hash(evaluation):
            raise ValueError("Experiment changed after review; a new independent review is required")
        created_by = created_by.strip()
        if not created_by or created_by in {protocol["created_by"], review["reviewed_by"]}:
            raise ValueError("Knowledge publisher must be independent from owner and reviewer")
        claim = self._required(claim, "Knowledge claim")
        mechanism = self._required(mechanism, "Causal mechanism")
        applicability = self._applicability(applicability)
        falsification_conditions = self._strings(falsification_conditions)
        if not falsification_conditions:
            raise ValueError("Knowledge requires explicit falsification conditions")
        evidence_ids = self._evidence(evidence_ids)
        valid_from_dt = self._datetime(valid_from, "valid_from")
        reevaluate_at_dt = self._datetime(reevaluate_at, "reevaluate_at")
        if reevaluate_at_dt <= valid_from_dt:
            raise ValueError("reevaluate_at must be after valid_from")
        parent = None
        scope_relation = None
        replication_rationale_clean = None
        if replicates_knowledge_id:
            parent = self.get(replicates_knowledge_id)
            if not parent["usable"]:
                raise ValueError("Replication source knowledge must still be usable")
            if parent["protocol_id"] == protocol_id:
                raise ValueError("A replication must use a distinct experiment protocol")
            if parent["claim"].casefold() != claim.casefold():
                raise ValueError("Replication claim must match the source knowledge claim")
            replication_rationale_clean = self._required(
                replication_rationale or "", "Replication rationale"
            )
            scope_relation = (
                "same_scope"
                if parent["applicability"] == applicability
                else "extended_scope"
            )
        effect_snapshot = {
            "evaluation_hash": review["evaluation_hash"],
            "primary_metric": protocol["primary_metric"],
            "treatment_effect": evaluation["treatment_effect"],
            "incremental_value_per_unit": evaluation["incremental_value_per_unit"],
            "heterogeneous_effects": evaluation["heterogeneous_effects"],
            "effect_metric_results": evaluation["effect_metric_results"],
        }
        canonical = {
            "protocol_id": protocol_id,
            "review_id": review_id,
            "claim": claim,
            "mechanism": mechanism,
            "applicability": applicability,
            "falsification_conditions": falsification_conditions,
            "effect_snapshot": effect_snapshot,
            "evidence_ids": evidence_ids,
            "valid_from": valid_from_dt.isoformat(),
            "reevaluate_at": reevaluate_at_dt.isoformat(),
            "created_by": created_by,
            "replicates_knowledge_id": replicates_knowledge_id,
            "replication_rationale": replication_rationale_clean,
        }
        request_hash = self._hash(canonical)
        with Session(self.engine) as session, session.begin():
            exact = session.scalar(
                select(CausalKnowledgeEntryRow).where(
                    CausalKnowledgeEntryRow.request_hash == request_hash
                )
            )
            if exact is not None:
                return self.get(exact.id)
            previous = session.scalar(
                select(CausalKnowledgeEntryRow).where(
                    CausalKnowledgeEntryRow.protocol_id == protocol_id
                )
            )
            if previous is not None:
                raise ValueError("Experiment already has an immutable causal knowledge entry")
            row = CausalKnowledgeEntryRow(
                id=new_id("cke"),
                request_hash=request_hash,
                protocol_id=protocol_id,
                review_id=review_id,
                claim=claim,
                mechanism=mechanism,
                applicability_json=applicability,
                falsification_conditions_json=falsification_conditions,
                effect_snapshot_json=effect_snapshot,
                evidence_json=evidence_ids,
                valid_from=valid_from_dt,
                reevaluate_at=reevaluate_at_dt,
                execution_eligible=False,
                created_by=created_by,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            knowledge_id = row.id
            if parent is not None:
                link_canonical = {
                    "source_knowledge_id": parent["id"],
                    "replication_knowledge_id": knowledge_id,
                    "scope_relation": scope_relation,
                    "rationale": replication_rationale_clean,
                    "created_by": created_by,
                }
                session.add(
                    CausalReplicationLinkRow(
                        id=new_id("crl"),
                        request_hash=self._hash(link_canonical),
                        source_knowledge_id=parent["id"],
                        replication_knowledge_id=knowledge_id,
                        scope_relation=scope_relation,
                        rationale=replication_rationale_clean,
                        created_by=created_by,
                        created_at=datetime.now(UTC),
                    )
                )
        self._link(evidence_ids, "causal_knowledge_entry", knowledge_id, created_by)
        return self.get(knowledge_id)

    def list_reviews(self, protocol_id: str) -> list[dict[str, Any]]:
        self.experiments.get(protocol_id)
        with Session(self.engine) as session:
            rows = list(
                session.scalars(
                    select(CausalExperimentReviewRow)
                    .where(CausalExperimentReviewRow.protocol_id == protocol_id)
                    .order_by(CausalExperimentReviewRow.created_at, CausalExperimentReviewRow.id)
                )
            )
        return [self._review(row) for row in rows]

    def get_review(self, review_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            row = session.get(CausalExperimentReviewRow, review_id)
            if row is None:
                raise KeyError(f"Causal experiment review not found: {review_id}")
            return self._review(row)

    def list(self, *, usable_only: bool = False) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            ids = list(
                session.scalars(
                    select(CausalKnowledgeEntryRow.id).order_by(
                        CausalKnowledgeEntryRow.created_at,
                        CausalKnowledgeEntryRow.id,
                    )
                )
            )
        results = [self.get(item_id) for item_id in ids]
        return [item for item in results if item["usable"]] if usable_only else results

    def get(self, knowledge_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            row = session.get(CausalKnowledgeEntryRow, knowledge_id)
            if row is None:
                raise KeyError(f"Causal knowledge entry not found: {knowledge_id}")
            outgoing = list(
                session.scalars(
                    select(CausalReplicationLinkRow).where(
                        CausalReplicationLinkRow.source_knowledge_id == knowledge_id
                    )
                )
            )
            incoming = session.scalar(
                select(CausalReplicationLinkRow).where(
                    CausalReplicationLinkRow.replication_knowledge_id == knowledge_id
                )
            )
            result = self._entry(row)
        current_evaluation = self.experiments.evaluate(result["protocol_id"])
        now = datetime.now(UTC)
        if now < self._as_utc(row.valid_from):
            validity_status = "not_yet_valid"
        elif not current_evaluation["review_eligible"]:
            validity_status = "source_experiment_invalidated"
        elif self._hash(current_evaluation) != result["effect_snapshot"]["evaluation_hash"]:
            validity_status = "source_evaluation_changed"
        elif now >= self._as_utc(row.reevaluate_at):
            validity_status = "expired"
        else:
            validity_status = "active"
        usable_replications = []
        for link in outgoing:
            child = self._entry_by_id(link.replication_knowledge_id)
            child_evaluation = self.experiments.evaluate(child["protocol_id"])
            child_active = (
                now >= self._datetime(child["valid_from"], "valid_from")
                and now < self._datetime(child["reevaluate_at"], "reevaluate_at")
                and child_evaluation["review_eligible"]
                and self._hash(child_evaluation)
                == child["effect_snapshot"]["evaluation_hash"]
            )
            if child_active:
                usable_replications.append(self._link_row(link))
        same_scope = any(item["scope_relation"] == "same_scope" for item in usable_replications)
        extended_scope = any(
            item["scope_relation"] == "extended_scope" for item in usable_replications
        )
        if same_scope and extended_scope:
            strength = "replicated_with_portability_signal"
        elif same_scope:
            strength = "replicated"
        elif extended_scope:
            strength = "portable_candidate"
        else:
            strength = "provisional"
        return {
            **result,
            "validity_status": validity_status,
            "usable": validity_status == "active",
            "knowledge_strength": strength,
            "replication_of": self._link_row(incoming) if incoming else None,
            "replications": [self._link_row(item) for item in outgoing],
            "usable_replication_count": len(usable_replications),
            "execution_eligible": False,
            "automatic_rollout": False,
        }

    def _entry_by_id(self, knowledge_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            row = session.get(CausalKnowledgeEntryRow, knowledge_id)
            if row is None:
                raise KeyError(f"Causal knowledge entry not found: {knowledge_id}")
            return self._entry(row)

    def _link(self, evidence_ids: list[str], target_type: str, target_id: str, actor: str) -> None:
        for evidence_id in evidence_ids:
            self.evidence.link(
                evidence_id=evidence_id,
                target_type=target_type,
                target_id=target_id,
                relationship="supports",
                created_by=actor,
            )

    def _evidence(self, values: list[str]) -> list[str]:
        normalized = sorted({item.strip() for item in values if item.strip()})
        if not normalized:
            raise ValueError("Evidence is required")
        self.evidence.require_valid(normalized)
        return normalized

    @staticmethod
    def _applicability(value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict) or not value:
            raise ValueError("Knowledge requires a non-empty applicability boundary")
        required = {"platform", "country", "category", "population"}
        missing = sorted(required - set(value))
        if missing:
            raise ValueError(f"Applicability boundary missing: {', '.join(missing)}")
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            key_clean = str(key).strip()
            if not key_clean or item is None or item == "":
                raise ValueError("Applicability keys and values must be non-empty")
            cleaned[key_clean] = item.strip() if isinstance(item, str) else item
        return cleaned

    @staticmethod
    def _required(value: str, name: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError(f"{name} is required")
        return cleaned

    @staticmethod
    def _strings(values: list[str]) -> list[str]:
        return [item.strip() for item in values if item.strip()]

    @staticmethod
    def _datetime(value: str, name: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{name} must be ISO-8601") from exc
        if parsed.tzinfo is None:
            raise ValueError(f"{name} must include timezone")
        return parsed.astimezone(UTC)

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @staticmethod
    def _hash(value: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()

    @classmethod
    def _review(cls, row: CausalExperimentReviewRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "protocol_id": row.protocol_id,
            "evaluation_hash": row.evaluation_hash,
            "evaluation": row.evaluation_json,
            "verdict": row.verdict,
            "rationale": row.rationale,
            "method_assessment": row.method_assessment,
            "data_quality_assessment": row.data_quality_assessment,
            "counterarguments": row.counterarguments_json,
            "evidence_ids": row.evidence_json,
            "reviewed_by": row.reviewed_by,
            "created_at": cls._as_utc(row.created_at).isoformat(),
            "immutable": True,
        }

    @classmethod
    def _entry(cls, row: CausalKnowledgeEntryRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "protocol_id": row.protocol_id,
            "review_id": row.review_id,
            "claim": row.claim,
            "mechanism": row.mechanism,
            "applicability": row.applicability_json,
            "falsification_conditions": row.falsification_conditions_json,
            "effect_snapshot": row.effect_snapshot_json,
            "evidence_ids": row.evidence_json,
            "valid_from": cls._as_utc(row.valid_from).isoformat(),
            "reevaluate_at": cls._as_utc(row.reevaluate_at).isoformat(),
            "execution_eligible": False,
            "created_by": row.created_by,
            "created_at": cls._as_utc(row.created_at).isoformat(),
            "immutable": True,
        }

    @classmethod
    def _link_row(cls, row: CausalReplicationLinkRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "source_knowledge_id": row.source_knowledge_id,
            "replication_knowledge_id": row.replication_knowledge_id,
            "scope_relation": row.scope_relation,
            "rationale": row.rationale,
            "created_by": row.created_by,
            "created_at": cls._as_utc(row.created_at).isoformat(),
        }

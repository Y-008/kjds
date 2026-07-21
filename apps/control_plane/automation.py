from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Numeric, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .numeric_semantics import finite_decimal
from .providers import OllamaProvider
from .repository import Repository
from .sql_repository import Base, add_outbox_event

RiskLevel = Literal["low", "medium", "high"]

KNOWN_MODEL_LICENSES = {
    "qwen2.5:3b": ("Apache-2.0", "allowed"),
    "nomic-embed-text:latest": ("Apache-2.0", "allowed"),
    "gemma2:2b": ("Gemma Terms", "review_required"),
    "llama3.2:1b": ("Llama Community License", "review_required"),
    "tinyllama:latest": ("Apache-2.0", "allowed"),
}


class ModelRegistryRow(Base):
    __tablename__ = "model_registry"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    provider: Mapped[str] = mapped_column(String)
    model_name: Mapped[str] = mapped_column(String)
    capability: Mapped[str] = mapped_column(String)
    license_name: Mapped[str] = mapped_column(String)
    commercial_status: Mapped[str] = mapped_column(String)
    enabled: Mapped[bool] = mapped_column(Boolean)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RecommendationRow(Base):
    __tablename__ = "decision_recommendations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    agent: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    rationale: Mapped[str] = mapped_column(Text)
    evidence_json: Mapped[list[str]] = mapped_column(JSON)
    expected_cm3_delta_decimal: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    risk: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    shadow_mode: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


@dataclass(frozen=True, slots=True)
class ModelProfile:
    id: str
    provider: str
    model_name: str
    capability: str
    license_name: str
    commercial_status: str
    enabled: bool
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Recommendation:
    id: str
    product_id: str | None
    agent: str
    action: str
    rationale: str
    evidence: list[str]
    expected_cm3_delta: Decimal | None
    risk: str
    status: str
    shadow_mode: bool
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AutomationService:
    def __init__(self, engine, repository: Repository, *, shadow_mode: bool = True) -> None:
        self.engine = engine
        self.repo = repository
        self.shadow_mode = shadow_mode

    def sync_ollama_models(self, provider: OllamaProvider) -> list[ModelProfile]:
        profiles: list[ModelProfile] = []
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            for item in provider.list_models():
                name = item["name"]
                license_name, commercial_status = KNOWN_MODEL_LICENSES.get(name, ("Unknown", "review_required"))
                row = session.scalar(
                    select(ModelRegistryRow).where(
                        ModelRegistryRow.provider == "ollama",
                        ModelRegistryRow.model_name == name,
                        ModelRegistryRow.capability == "language_or_embedding",
                    )
                )
                metadata = {
                    "size": item.get("size"),
                    "digest": item.get("digest"),
                    "modified_at": item.get("modified_at"),
                }
                if row is None:
                    row = ModelRegistryRow(
                        id=new_id("mdl"),
                        provider="ollama",
                        model_name=name,
                        capability="language_or_embedding",
                        license_name=license_name,
                        commercial_status=commercial_status,
                        enabled=commercial_status == "allowed" and name in {"qwen2.5:3b", "nomic-embed-text:latest"},
                        metadata_json=metadata,
                        created_at=datetime.now(UTC),
                    )
                    session.add(row)
                else:
                    row.license_name = license_name
                    row.commercial_status = commercial_status
                    row.metadata_json = metadata
                profiles.append(self._model(row))
        return profiles

    def list_models(self) -> list[ModelProfile]:
        with Session(self.engine) as session:
            rows = session.scalars(
                select(ModelRegistryRow).order_by(ModelRegistryRow.provider, ModelRegistryRow.model_name)
            ).all()
            return [self._model(row) for row in rows]

    def create_recommendation(
        self,
        *,
        product_id: str | None,
        agent: str,
        action: str,
        rationale: str,
        evidence: list[str],
        expected_cm3_delta: Decimal | None,
        risk: RiskLevel,
    ) -> Recommendation:
        if product_id:
            self.repo.get_product(product_id)
        if not evidence:
            raise ValueError("Recommendation requires evidence")
        if not rationale.strip() or not action.strip():
            raise ValueError("Recommendation requires an action and rationale")
        if expected_cm3_delta is not None:
            expected_cm3_delta = finite_decimal(expected_cm3_delta, "Expected CM3 delta")
        row = RecommendationRow(
            id=new_id("rec"),
            product_id=product_id,
            agent=agent,
            action=action,
            rationale=rationale,
            evidence_json=evidence,
            expected_cm3_delta_decimal=expected_cm3_delta,
            risk=risk,
            status="observing" if self.shadow_mode else "proposed",
            shadow_mode=self.shadow_mode,
            created_at=datetime.now(UTC),
            decided_at=None,
        )
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            session.add(row)
            add_outbox_event(
                session,
                "decision.recommended",
                row.id,
                {"agent": agent, "action": action, "risk": risk, "shadow_mode": self.shadow_mode},
            )
        return self._recommendation(row)

    def list_recommendations(self) -> list[Recommendation]:
        with Session(self.engine) as session:
            rows = session.scalars(select(RecommendationRow).order_by(RecommendationRow.created_at.desc())).all()
            return [self._recommendation(row) for row in rows]

    @staticmethod
    def _model(row: ModelRegistryRow) -> ModelProfile:
        return ModelProfile(
            row.id,
            row.provider,
            row.model_name,
            row.capability,
            row.license_name,
            row.commercial_status,
            row.enabled,
            row.metadata_json,
        )

    @staticmethod
    def _recommendation(row: RecommendationRow) -> Recommendation:
        return Recommendation(
            row.id,
            row.product_id,
            row.agent,
            row.action,
            row.rationale,
            row.evidence_json,
            row.expected_cm3_delta_decimal,
            row.risk,
            row.status,
            row.shadow_mode,
            row.created_at.isoformat(),
        )

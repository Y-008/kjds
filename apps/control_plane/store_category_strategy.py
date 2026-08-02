from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .evidence import EvidenceGrade
from .security import Principal
from .sql_repository import Base

REGISTRY_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "project"
    / "registries"
    / "store_category_strategy_registry.json"
)


class StoreCategoryStrategyConflict(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("as_of must include a timezone")
    return value.astimezone(UTC)


def _required(value: Any, field: str, max_length: int) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    return normalized


def _optional(value: Any, field: str, max_length: int) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    return normalized


def _decimal(value: Any) -> Decimal | None:
    if value in (None, "", "no_data"):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


class StoreOperatingProfileRow(Base):
    __tablename__ = "store_operating_profile_events"
    __table_args__ = (
        UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "idempotency_key",
            name="uq_store_operating_profile_scope_idempotency",
        ),
        CheckConstraint(
            "length(scope_grant_authority_sha256) = 64 "
            "AND length(request_sha256) = 64 "
            "AND length(profile_sha256) = 64",
            name="ck_store_operating_profile_hashes",
        ),
        CheckConstraint(
            "confirmed IS TRUE AND external_write_allowed IS FALSE",
            name="ck_store_operating_profile_control",
        ),
        Index(
            "ix_store_operating_profile_scope_effective",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "effective_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(180), primary_key=True)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(180), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    request_evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_records.id"), nullable=False
    )
    supporting_evidence_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    external_write_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(240), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StoreOperatingPlanSnapshotRow(Base):
    __tablename__ = "store_operating_plan_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "idempotency_key",
            name="uq_store_operating_plan_scope_idempotency",
        ),
        CheckConstraint(
            "length(scope_grant_authority_sha256) = 64 "
            "AND length(input_snapshot_sha256) = 64 "
            "AND length(output_snapshot_sha256) = 64",
            name="ck_store_operating_plan_hashes",
        ),
        CheckConstraint(
            "status IN ('ready_with_constraints','no_data','blocked')",
            name="ck_store_operating_plan_status",
        ),
        CheckConstraint(
            "external_write_allowed IS FALSE",
            name="ck_store_operating_plan_control",
        ),
        Index(
            "ix_store_operating_plan_scope_created",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(180), primary_key=True)
    profile_id: Mapped[str | None] = mapped_column(
        ForeignKey("store_operating_profile_events.id"), nullable=True
    )
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(180), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    input_snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    output_snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    evidence_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    external_write_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_by: Mapped[str] = mapped_column(String(240), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StoreCategoryStrategyRegistry:
    def __init__(self, path: Path | None = None, *, as_of: date | None = None) -> None:
        self.path = path or REGISTRY_PATH
        self.raw = json.loads(self.path.read_text(encoding="utf-8"))
        if self.raw.get("registry_id") != "kjds-store-category-strategy-v1":
            raise RuntimeError("Unknown store category strategy registry")
        selected = as_of or date.today()
        start = date.fromisoformat(self.raw["effective_from"])
        end = (
            date.fromisoformat(self.raw["effective_to"])
            if self.raw.get("effective_to")
            else None
        )
        if selected < start or (end is not None and selected > end):
            raise RuntimeError("No store category strategy registry is effective for as_of")
        self.registry_sha256 = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.positionings = frozenset(self.raw["store_positionings"])
        self.assortment_modes = frozenset(self.raw["assortment_modes"])
        self.price_bands = frozenset(self.raw["price_bands"])
        self.category_roles = frozenset(self.raw["category_roles"])
        self.growth_channels = frozenset(self.raw["growth_channels"])
        self.archetypes = self.raw["derived_archetypes"]

    def snapshot(self) -> dict[str, Any]:
        return {
            "registry_id": self.raw["registry_id"],
            "version": self.raw["version"],
            "status": self.raw["status"],
            "effective_from": self.raw["effective_from"],
            "effective_to": self.raw.get("effective_to"),
            "registry_sha256": self.registry_sha256,
            "official_taxonomy_semantics": self.raw[
                "official_taxonomy_semantics"
            ],
            "derived_tag_semantics": self.raw["derived_tag_semantics"],
            "derived_archetypes": self.archetypes,
            "routing_precedence": self.raw["routing_precedence"],
            "control_envelope": self.raw["control_envelope"],
        }


class StoreCategoryStrategyWorkspace:
    CONTRACT_ID = "kjds-store-category-profit-strategy-v1"
    PROFILE_CONTRACT_ID = "kjds-store-operating-profile-event-v1"
    PLAN_CONTRACT_ID = "kjds-store-operating-plan-snapshot-v1"

    def __init__(self, *, engine, evidence, registry=None) -> None:
        self.engine = engine
        self.evidence = evidence
        self.registry = registry or StoreCategoryStrategyRegistry()

    def capture_profile(
        self,
        request: dict[str, Any],
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        cutoff = _utc(as_of)
        scope = self._scope(principal, entity_scope, store_ref)
        values = dict(request)
        key = _required(values.pop("idempotency_key", None), "idempotency_key", 180)
        if values.pop("confirmed", None) is not True:
            raise ValueError("confirmed must be true")
        supporting = sorted(
            {
                _required(item, "supporting_evidence_id", 180)
                for item in values.pop("supporting_evidence_ids", [])
            }
        )
        self._require_supporting_evidence(
            supporting,
            principal=principal,
            store_ref=store_ref,
            as_of=cutoff,
        )
        profile = self._normalize_profile(values)
        request_core = {
            "contract_id": self.PROFILE_CONTRACT_ID,
            "scope": scope,
            "profile": profile,
            "supporting_evidence_ids": supporting,
            "effective_at": cutoff.isoformat(),
            "confirmed": True,
        }
        request_sha = _sha256(request_core)
        profile_sha = _sha256(profile)

        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            existing = session.scalar(
                select(StoreOperatingProfileRow).where(
                    StoreOperatingProfileRow.tenant_ref == scope["tenant_ref"],
                    StoreOperatingProfileRow.entity_ref == scope["entity_ref"],
                    StoreOperatingProfileRow.store_ref == scope["store_ref"],
                    StoreOperatingProfileRow.idempotency_key == key,
                )
            )
            if existing is not None:
                if existing.request_sha256 != request_sha:
                    raise StoreCategoryStrategyConflict(
                        "Store profile idempotency key already has different immutable content"
                    )
                return self._profile_result(existing, idempotent=True)

            content = _canonical(request_core)
            evidence = self.evidence.capture(
                content=content,
                filename=f"store-operating-profile-{store_ref}-{key}.json",
                content_type="application/json",
                source="store_operating_profile_request",
                source_ref=(
                    f"{scope['tenant_ref']}:{scope['entity_ref']}:{store_ref}:{key}"
                ),
                grade=EvidenceGrade.C,
                effective_at=cutoff.isoformat(),
                effective_until=None,
                created_by=principal.actor_id,
                metadata={
                    "contract_id": self.PROFILE_CONTRACT_ID,
                    **scope,
                    "request_sha256": request_sha,
                    "profile_sha256": profile_sha,
                    "formal_fact": False,
                    "external_write_allowed": False,
                },
                _session=session,
            )
            row = StoreOperatingProfileRow(
                id=new_id("sop"),
                tenant_ref=scope["tenant_ref"],
                entity_ref=scope["entity_ref"],
                store_ref=scope["store_ref"],
                scope_grant_authority_sha256=scope[
                    "scope_grant_authority_sha256"
                ],
                idempotency_key=key,
                request_sha256=request_sha,
                profile_sha256=profile_sha,
                profile_json=profile,
                request_evidence_id=evidence.id,
                supporting_evidence_ids_json=supporting,
                confirmed=True,
                external_write_allowed=False,
                effective_at=cutoff,
                created_by=principal.actor_id,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            return self._profile_result(row, idempotent=False)

    def current_profile(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        cutoff = _utc(as_of)
        scope = self._scope(principal, entity_scope, store_ref)
        with Session(self.engine) as session:
            row = session.scalar(
                select(StoreOperatingProfileRow)
                .where(
                    StoreOperatingProfileRow.tenant_ref == scope["tenant_ref"],
                    StoreOperatingProfileRow.entity_ref == scope["entity_ref"],
                    StoreOperatingProfileRow.store_ref == scope["store_ref"],
                    StoreOperatingProfileRow.effective_at <= cutoff,
                )
                .order_by(
                    StoreOperatingProfileRow.effective_at.desc(),
                    StoreOperatingProfileRow.created_at.desc(),
                )
            )
            if row is None:
                return {
                    "contract_id": self.PROFILE_CONTRACT_ID,
                    "status": "no_data",
                    "scope": scope,
                    "as_of": cutoff.isoformat(),
                    "profile": None,
                    "reason_codes": ["store_operating_profile_missing"],
                    "registry": self.registry.snapshot(),
                    "external_write_allowed": False,
                }
            return self._profile_result(row, idempotent=True)

    def compile_plan(
        self,
        workspace: dict[str, Any],
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        cutoff = _utc(as_of)
        scope = self._scope(principal, entity_scope, store_ref)
        current = self.current_profile(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=cutoff,
        )
        profile = current.get("profile")
        candidates = [
            self.compile_candidate(candidate, profile=profile)
            for candidate in workspace.get("candidates") or []
        ]
        route_states = (
            "primary_store",
            "adjacent_category_limited",
            "pilot_only",
            "blocked",
            "needs_category_data",
        )
        route_counts = {
            state: sum(
                candidate["store_category_route"]["decision"] == state
                for candidate in candidates
            )
            for state in route_states
        }
        status = (
            "no_data"
            if profile is None
            else "ready_with_constraints"
            if candidates
            else "no_data"
        )
        evidence_ids = sorted(
            {
                *(current.get("evidence_ids") or []),
                *(
                    evidence_id
                    for candidate in candidates
                    for evidence_id in candidate.get("evidence_ids") or []
                ),
            }
        )
        input_core = {
            "scope": scope,
            "as_of": cutoff.isoformat(),
            "registry_sha256": self.registry.registry_sha256,
            "profile_sha256": current.get("profile_sha256"),
            "profit_snapshot_sha256": workspace.get("snapshot_sha256"),
        }
        payload = {
            "contract_id": self.CONTRACT_ID,
            "status": status,
            "scope": scope,
            "as_of": cutoff.isoformat(),
            "profile": profile,
            "profile_id": current.get("profile_id"),
            "profile_status": current.get("status"),
            "registry": self.registry.snapshot(),
            "summary": {
                "candidate_count": len(candidates),
                "route_counts": route_counts,
                "highest_value_action": (workspace.get("summary") or {}).get(
                    "highest_value_action"
                ),
                "actual_cash_profit": (workspace.get("summary") or {}).get(
                    "actual_cash_profit"
                ),
                "data_freshness": (workspace.get("summary") or {}).get(
                    "data_freshness"
                ),
            },
            "category_tree": self._category_tree(profile, candidates),
            "candidates": candidates,
            "reason_codes": (
                ["store_operating_profile_missing"] if profile is None else []
            ),
            "evidence_ids": evidence_ids,
            "input_snapshot_sha256": _sha256(input_core),
            "control_envelope": {
                "proposal_only": True,
                "derived_tag_is_official_taxonomy": False,
                "formal_fact_promoted": False,
                "automatic_cross_store_publish": False,
                "automatic_advertising": False,
                "automatic_procurement": False,
                "approval_created": False,
                "permit_created": False,
                "external_write_allowed": False,
            },
        }
        payload["snapshot_sha256"] = _sha256(payload)
        return payload

    def compile_candidate(
        self,
        candidate: dict[str, Any],
        *,
        profile: dict[str, Any] | None,
    ) -> dict[str, Any]:
        category = candidate.get("category_identity") or {}
        paths = profile.get("category_paths") if profile else []
        matches = [
            self._match_path(category, path)
            for path in paths or []
        ]
        matches = [match for match in matches if match["matched"]]
        exact_exclusions = [
            match
            for match in matches
            if match["role"] == "excluded" and match["official_match"]
        ]
        selected = None
        if exact_exclusions:
            selected = sorted(
                exact_exclusions,
                key=lambda item: (-item["specificity"], item["path_id"]),
            )[0]
        elif matches:
            role_rank = {"core": 0, "adjacent": 1, "experimental": 2, "excluded": 3}
            selected = sorted(
                matches,
                key=lambda item: (
                    -item["specificity"],
                    role_rank[item["role"]],
                    item["path_id"],
                ),
            )[0]

        if profile is None:
            decision = "needs_category_data"
            confidence = "no_data"
            reasons = ["store_operating_profile_missing"]
        elif selected is None:
            decision = "needs_category_data"
            confidence = "no_match"
            reasons = ["official_store_category_match_missing"]
        elif selected["role"] == "excluded":
            decision = "blocked"
            confidence = selected["confidence"]
            reasons = ["store_category_explicitly_excluded"]
        elif not selected["official_match"]:
            decision = "needs_category_data"
            confidence = "derived_advisory_only"
            reasons = ["derived_tag_cannot_create_official_category_route"]
        else:
            decision = {
                "core": "primary_store",
                "adjacent": "adjacent_category_limited",
                "experimental": "pilot_only",
            }[selected["role"]]
            confidence = selected["confidence"]
            reasons = []

        tags = selected["derived_tags"] if selected else []
        lifecycle = self._lifecycle(candidate)
        mode = self._operating_mode(profile, tags, lifecycle)
        reasons.extend(candidate.get("reason_codes") or [])
        if lifecycle == "research":
            reasons.append("profit_evidence_not_ready_for_distribution")
        target_path = selected["official_path"] if selected and selected["official_match"] else None
        channels = (
            sorted(set(profile.get("planned_growth_channels") or []) | {"ozon"})
            if profile and decision not in {"blocked", "needs_category_data"}
            else []
        )
        archetype_contracts = {
            tag: self.registry.archetypes[tag]
            for tag in tags
            if tag in self.registry.archetypes
        }
        playbook = {
            "lifecycle": lifecycle,
            "operating_mode": mode,
            "listing": self._listing_action(decision, lifecycle),
            "traffic": self._traffic_action(decision, lifecycle),
            "inventory": self._inventory_action(decision, lifecycle),
            "growth_channels": channels,
            "required_gates": sorted(
                {
                    gate
                    for contract in archetype_contracts.values()
                    for gate in contract["required_gates"]
                }
            ),
            "focus_metrics": sorted(
                {
                    metric
                    for contract in archetype_contracts.values()
                    for metric in contract["focus_metrics"]
                }
            ),
            "next_action": candidate.get("next_action"),
            "budget_limit": candidate.get("budget_limit"),
            "stop_loss_condition": candidate.get("stop_loss_condition"),
        }
        strategy = {
            "decision": decision,
            "confidence": confidence,
            "target_store_ref": (
                profile.get("store_ref")
                if profile and decision not in {"blocked", "needs_category_data"}
                else None
            ),
            "target_category_path": target_path,
            "category_role": selected["role"] if selected else None,
            "match_basis": selected["basis"] if selected else [],
            "derived_tags": tags,
            "derived_tags_are_official_taxonomy": False,
            "reason_codes": sorted(set(reasons)),
            "playbook": playbook,
            "external_write_allowed": False,
        }
        return {
            **candidate,
            "store_category_route": strategy,
            "evidence_ids": sorted(
                {
                    *(candidate.get("evidence_ids") or []),
                    *(
                        [profile["request_evidence_id"]]
                        if profile and profile.get("request_evidence_id")
                        else []
                    ),
                }
            ),
        }

    def compile_store_matrix(
        self,
        contexts: list[dict[str, Any]],
        *,
        tenant_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        cutoff = _utc(as_of)
        profiles = [
            {
                "store_ref": context["store_ref"],
                "profile": context.get("profile"),
                "profile_status": context.get("profile_status", "no_data"),
                "scope_status": context.get("scope_status", "no_data"),
            }
            for context in contexts
        ]
        candidates = [
            (context["store_ref"], candidate)
            for context in contexts
            for candidate in (context.get("workspace") or {}).get("candidates", [])
        ]
        decision_rank = {
            "primary_store": 0,
            "adjacent_category_limited": 1,
            "pilot_only": 2,
        }
        confidence_rank = {
            "exact_leaf": 0,
            "exact_product_type": 1,
            "exact_hierarchy": 2,
        }
        routes = []
        for source_store_ref, candidate in candidates:
            alternatives = []
            for profile_context in profiles:
                profile = profile_context["profile"]
                if profile is None or profile_context["scope_status"] != "ready":
                    continue
                projected = self.compile_candidate(candidate, profile=profile)
                route = projected["store_category_route"]
                alternatives.append(
                    {
                        "store_ref": profile_context["store_ref"],
                        "decision": route["decision"],
                        "confidence": route["confidence"],
                        "target_category_path": route["target_category_path"],
                        "category_role": route["category_role"],
                        "reason_codes": route["reason_codes"],
                    }
                )
            viable = [
                item for item in alternatives if item["decision"] in decision_rank
            ]
            selected = (
                sorted(
                    viable,
                    key=lambda item: (
                        decision_rank[item["decision"]],
                        confidence_rank.get(item["confidence"], 9),
                        item["store_ref"] != source_store_ref,
                        item["store_ref"],
                    ),
                )[0]
                if viable
                else None
            )
            routes.append(
                {
                    "candidate_id": candidate.get("candidate_id"),
                    "offer_id": candidate.get("offer_id"),
                    "name": candidate.get("name"),
                    "source_store_ref": source_store_ref,
                    "recommended_store_ref": (
                        selected["store_ref"] if selected else None
                    ),
                    "recommended_route": selected,
                    "cross_store_handoff_required": bool(
                        selected and selected["store_ref"] != source_store_ref
                    ),
                    "alternatives": sorted(
                        alternatives,
                        key=lambda item: (
                            decision_rank.get(item["decision"], 9),
                            confidence_rank.get(item["confidence"], 9),
                            item["store_ref"],
                        ),
                    ),
                    "external_write_allowed": False,
                }
            )
        payload = {
            "contract_id": "kjds-cross-store-category-routing-v1",
            "status": "ready_with_constraints" if routes else "no_data",
            "tenant_ref": tenant_ref,
            "as_of": cutoff.isoformat(),
            "store_coverage": [
                {
                    "store_ref": item["store_ref"],
                    "scope_status": item["scope_status"],
                    "profile_status": item["profile_status"],
                }
                for item in profiles
            ],
            "routes": routes,
            "control_envelope": {
                "proposal_only": True,
                "automatic_cross_store_publish": False,
                "listing_created": False,
                "approval_created": False,
                "permit_created": False,
                "external_write_allowed": False,
            },
        }
        payload["snapshot_sha256"] = _sha256(payload)
        return payload

    def freeze_plan(
        self,
        plan: dict[str, Any],
        *,
        idempotency_key: str,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        cutoff = _utc(as_of)
        scope = self._scope(principal, entity_scope, store_ref)
        key = _required(idempotency_key, "idempotency_key", 180)
        if plan.get("scope", {}).get("tenant_ref") != scope["tenant_ref"] or plan.get(
            "scope", {}
        ).get("entity_ref") != scope["entity_ref"] or plan.get("scope", {}).get(
            "store_ref"
        ) != scope["store_ref"]:
            raise PermissionError("Operating plan scope does not match authorized scope")
        input_sha = _required(
            plan.get("input_snapshot_sha256"), "input_snapshot_sha256", 64
        )
        output_sha = _required(plan.get("snapshot_sha256"), "snapshot_sha256", 64)
        request_sha = _sha256(
            {
                "scope": scope,
                "idempotency_key": key,
                "input_snapshot_sha256": input_sha,
                "output_snapshot_sha256": output_sha,
            }
        )
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            existing = session.scalar(
                select(StoreOperatingPlanSnapshotRow).where(
                    StoreOperatingPlanSnapshotRow.tenant_ref == scope["tenant_ref"],
                    StoreOperatingPlanSnapshotRow.entity_ref == scope["entity_ref"],
                    StoreOperatingPlanSnapshotRow.store_ref == scope["store_ref"],
                    StoreOperatingPlanSnapshotRow.idempotency_key == key,
                )
            )
            if existing is not None:
                existing_request_sha = _sha256(
                    {
                        "scope": scope,
                        "idempotency_key": key,
                        "input_snapshot_sha256": existing.input_snapshot_sha256,
                        "output_snapshot_sha256": existing.output_snapshot_sha256,
                    }
                )
                if existing_request_sha != request_sha:
                    raise StoreCategoryStrategyConflict(
                        "Operating plan idempotency key already has different immutable content"
                    )
                return self._plan_snapshot(existing, idempotent=True)
            row = StoreOperatingPlanSnapshotRow(
                id=new_id("sps"),
                profile_id=plan.get("profile_id"),
                tenant_ref=scope["tenant_ref"],
                entity_ref=scope["entity_ref"],
                store_ref=scope["store_ref"],
                scope_grant_authority_sha256=scope[
                    "scope_grant_authority_sha256"
                ],
                idempotency_key=key,
                status=plan.get("status", "no_data"),
                input_snapshot_sha256=input_sha,
                output_snapshot_sha256=output_sha,
                snapshot_json=plan,
                evidence_ids_json=plan.get("evidence_ids") or [],
                as_of=cutoff,
                external_write_allowed=False,
                created_by=principal.actor_id,
                created_at=datetime.now(UTC),
            )
            session.add(row)
            session.flush()
            return self._plan_snapshot(row, idempotent=False)

    def get_plan_snapshot(
        self,
        snapshot_id: str,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
    ) -> dict[str, Any]:
        scope = self._scope(principal, entity_scope, store_ref)
        with Session(self.engine) as session:
            row = session.get(StoreOperatingPlanSnapshotRow, snapshot_id)
            if row is None or (
                row.tenant_ref,
                row.entity_ref,
                row.store_ref,
            ) != (scope["tenant_ref"], scope["entity_ref"], scope["store_ref"]):
                raise KeyError("Operating plan snapshot not found in authorized scope")
            return self._plan_snapshot(row, idempotent=True)

    def _normalize_profile(self, values: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "store_positioning",
            "assortment_mode",
            "price_band",
            "target_regions",
            "fulfillment_models",
            "planned_growth_channels",
            "customer_segments",
            "operational_capabilities",
            "category_paths",
        }
        unknown = sorted(set(values) - allowed)
        if unknown:
            raise ValueError(f"Unsupported store profile fields: {', '.join(unknown)}")
        positioning = _required(
            values.get("store_positioning"), "store_positioning", 80
        )
        mode = _required(values.get("assortment_mode"), "assortment_mode", 80)
        price_band = _required(values.get("price_band"), "price_band", 40)
        if positioning not in self.registry.positionings:
            raise ValueError("store_positioning is not registered")
        if mode not in self.registry.assortment_modes:
            raise ValueError("assortment_mode is not registered")
        if price_band not in self.registry.price_bands:
            raise ValueError("price_band is not registered")
        channels = self._string_list(
            values.get("planned_growth_channels") or [],
            "planned_growth_channels",
            maximum=3,
        )
        if not set(channels) <= self.registry.growth_channels:
            raise ValueError("planned_growth_channels contains an unregistered channel")
        paths_raw = values.get("category_paths")
        if not isinstance(paths_raw, list) or not paths_raw or len(paths_raw) > 200:
            raise ValueError("category_paths must contain between 1 and 200 paths")
        paths = [self._normalize_path(item) for item in paths_raw]
        path_ids = [item["path_id"] for item in paths]
        if len(path_ids) != len(set(path_ids)):
            raise ValueError("category path_id values must be unique")
        return {
            "store_positioning": positioning,
            "assortment_mode": mode,
            "price_band": price_band,
            "target_regions": self._string_list(
                values.get("target_regions") or [], "target_regions", maximum=100
            ),
            "fulfillment_models": self._string_list(
                values.get("fulfillment_models") or [],
                "fulfillment_models",
                maximum=20,
            ),
            "planned_growth_channels": channels,
            "customer_segments": self._string_list(
                values.get("customer_segments") or [],
                "customer_segments",
                maximum=50,
            ),
            "operational_capabilities": self._string_list(
                values.get("operational_capabilities") or [],
                "operational_capabilities",
                maximum=100,
            ),
            "category_paths": paths,
        }

    def _normalize_path(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("Every category path must be an object")
        allowed = {
            "path_id",
            "role",
            "level_1",
            "level_2",
            "level_3",
            "leaf_category_id",
            "product_type_ids",
            "derived_tags",
            "target_regions",
        }
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"Unsupported category path fields: {', '.join(unknown)}")
        role = _required(value.get("role"), "category role", 40)
        if role not in self.registry.category_roles:
            raise ValueError("category role is not registered")
        levels = {
            name: self._normalize_level(value.get(name), name)
            for name in ("level_1", "level_2", "level_3")
        }
        leaf = _optional(value.get("leaf_category_id"), "leaf_category_id", 160)
        types = self._string_list(
            value.get("product_type_ids") or [], "product_type_ids", maximum=200
        )
        tags = self._string_list(
            value.get("derived_tags") or [], "derived_tags", maximum=50
        )
        unknown_tags = sorted(set(tags) - set(self.registry.archetypes))
        if unknown_tags:
            raise ValueError(
                f"Unregistered derived category tags: {', '.join(unknown_tags)}"
            )
        if not leaf and not types and not any(levels.values()):
            raise ValueError(
                "Category path requires official hierarchy, leaf_category_id, or product_type_ids"
            )
        return {
            "path_id": _required(value.get("path_id"), "path_id", 160),
            "role": role,
            **levels,
            "leaf_category_id": leaf,
            "product_type_ids": types,
            "derived_tags": tags,
            "target_regions": self._string_list(
                value.get("target_regions") or [],
                "category target_regions",
                maximum=100,
            ),
        }

    @staticmethod
    def _normalize_level(value: Any, field: str) -> dict[str, str] | None:
        if value is None:
            return None
        if not isinstance(value, dict) or set(value) - {"id", "name"}:
            raise ValueError(f"{field} must contain only id and name")
        level_id = _required(value.get("id"), f"{field}.id", 160)
        name = _required(value.get("name"), f"{field}.name", 300)
        return {"id": level_id, "name": name}

    @staticmethod
    def _string_list(value: Any, field: str, *, maximum: int) -> list[str]:
        if not isinstance(value, list) or len(value) > maximum:
            raise ValueError(f"{field} must be a list with at most {maximum} values")
        result = []
        for item in value:
            normalized = _required(item, field, 300)
            if normalized not in result:
                result.append(normalized)
        return sorted(result)

    def _require_supporting_evidence(
        self,
        evidence_ids: list[str],
        *,
        principal: Principal,
        store_ref: str,
        as_of: datetime,
    ) -> None:
        if not evidence_ids:
            return
        self.evidence.require_current(evidence_ids, as_of=as_of)
        for evidence_id in evidence_ids:
            record = self.evidence.get_metadata(evidence_id)
            metadata = record.metadata or {}
            if metadata.get("tenant_ref") not in (None, principal.tenant_ref):
                raise PermissionError("Supporting Evidence tenant scope does not match")
            if metadata.get("store_ref") not in (None, store_ref):
                raise PermissionError("Supporting Evidence store scope does not match")

    @staticmethod
    def _scope(
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
    ) -> dict[str, str]:
        store = _required(store_ref, "store_ref", 160)
        if not principal.can_access_store(store):
            raise PermissionError("Store is outside the authenticated scope")
        if entity_scope.get("status") != "ready":
            raise PermissionError("Entity scope authority is not ready")
        entity = _required(entity_scope.get("entity_ref"), "entity_ref", 160)
        authority = _required(
            entity_scope.get("authority_sha256"),
            "scope_grant_authority_sha256",
            64,
        ).lower()
        if len(authority) != 64 or any(
            character not in "0123456789abcdef" for character in authority
        ):
            raise PermissionError("Scope grant authority hash is invalid")
        return {
            "tenant_ref": principal.tenant_ref,
            "entity_ref": entity,
            "store_ref": store,
            "scope_grant_authority_sha256": authority,
        }

    def _profile_result(
        self, row: StoreOperatingProfileRow, *, idempotent: bool
    ) -> dict[str, Any]:
        profile = {
            **row.profile_json,
            "store_ref": row.store_ref,
            "request_evidence_id": row.request_evidence_id,
        }
        return {
            "contract_id": self.PROFILE_CONTRACT_ID,
            "status": "ready",
            "profile_id": row.id,
            "profile_sha256": row.profile_sha256,
            "scope": {
                "tenant_ref": row.tenant_ref,
                "entity_ref": row.entity_ref,
                "store_ref": row.store_ref,
                "scope_grant_authority_sha256": row.scope_grant_authority_sha256,
            },
            "effective_at": row.effective_at.isoformat(),
            "profile": profile,
            "request_evidence_id": row.request_evidence_id,
            "evidence_ids": sorted(
                {row.request_evidence_id, *row.supporting_evidence_ids_json}
            ),
            "registry": self.registry.snapshot(),
            "idempotent": idempotent,
            "formal_fact_promoted": False,
            "external_write_allowed": False,
        }

    @staticmethod
    def _candidate_hierarchy(category: dict[str, Any]) -> dict[str, str | None]:
        hierarchy = category.get("hierarchy")
        if not isinstance(hierarchy, dict):
            hierarchy = {}
        return {
            level: _optional(hierarchy.get(level), level, 160)
            for level in ("level_1_id", "level_2_id", "level_3_id")
        }

    def _match_path(
        self, category: dict[str, Any], path: dict[str, Any]
    ) -> dict[str, Any]:
        source_leaf = _optional(
            category.get("source_category_id"), "source_category_id", 160
        )
        product_type = _optional(
            category.get("product_type_id"), "product_type_id", 160
        )
        hierarchy = self._candidate_hierarchy(category)
        candidate_tags = set(category.get("derived_tags") or [])
        path_tags = set(path.get("derived_tags") or [])
        basis = []
        specificity = 0
        if source_leaf and source_leaf == path.get("leaf_category_id"):
            basis.append("exact_leaf_category")
            specificity = max(specificity, 70)
        if product_type and product_type in path.get("product_type_ids", []):
            basis.append("exact_product_type")
            specificity = max(specificity, 60)
        for level, score in (("level_3", 50), ("level_2", 40), ("level_1", 30)):
            expected = path.get(level)
            if expected and expected["id"] == hierarchy[f"{level}_id"]:
                basis.append(f"exact_hierarchy_{level}")
                specificity = max(specificity, score)
        tag_matches = sorted(candidate_tags & path_tags)
        if tag_matches:
            basis.append("derived_tag_advisory")
            specificity = max(specificity, 10)
        official_match = any(not item.startswith("derived_") for item in basis)
        confidence = (
            "exact_leaf"
            if "exact_leaf_category" in basis
            else "exact_product_type"
            if "exact_product_type" in basis
            else "exact_hierarchy"
            if official_match
            else "derived_advisory_only"
        )
        return {
            "matched": bool(basis),
            "official_match": official_match,
            "specificity": specificity,
            "confidence": confidence,
            "basis": basis,
            "path_id": path["path_id"],
            "role": path["role"],
            "derived_tags": path.get("derived_tags") or [],
            "official_path": {
                key: path.get(key)
                for key in (
                    "path_id",
                    "level_1",
                    "level_2",
                    "level_3",
                    "leaf_category_id",
                    "product_type_ids",
                )
            },
        }

    @staticmethod
    def _lifecycle(candidate: dict[str, Any]) -> str:
        decision = candidate.get("decision_class")
        profit = candidate.get("profit") or {}
        cash = profit.get("cash_profit") or {}
        cash_amount = _decimal(cash.get("amount"))
        if decision in {"stop_loss", "exit"} or (
            cash.get("status") == "available"
            and cash_amount is not None
            and cash_amount <= 0
        ):
            return "exit"
        if cash.get("status") == "available" and cash_amount is not None and cash_amount > 0:
            return "growth"
        if decision == "pilot":
            return "pilot"
        scenario = profit.get("risk_adjusted_profit") or {}
        downside = _decimal(scenario.get("downside_cm3"))
        if downside is not None and downside > 0:
            return "qualified"
        return "research"

    def _operating_mode(
        self,
        profile: dict[str, Any] | None,
        tags: list[str],
        lifecycle: str,
    ) -> str | None:
        if profile is None:
            return None
        configured = profile["assortment_mode"]
        if lifecycle == "exit":
            return configured
        preferred = [
            mode
            for tag in tags
            for mode in self.registry.archetypes[tag]["preferred_modes"]
        ]
        if configured in preferred or not preferred:
            return configured
        if "refined_operation" in preferred:
            return "refined_operation"
        return preferred[0]

    @staticmethod
    def _listing_action(decision: str, lifecycle: str) -> str:
        if decision == "blocked" or lifecycle == "exit":
            return "do_not_list_or_stop_expansion"
        if decision == "needs_category_data" or lifecycle == "research":
            return "hold_until_official_category_and_profit_evidence"
        if lifecycle in {"qualified", "pilot"}:
            return "prepare_independently_approved_small_pilot"
        return "maintain_and_optimize_existing_listing"

    @staticmethod
    def _traffic_action(decision: str, lifecycle: str) -> str:
        if decision in {"blocked", "needs_category_data"} or lifecycle in {
            "research",
            "exit",
        }:
            return "no_traffic_expansion"
        if lifecycle in {"qualified", "pilot"}:
            return "proposal_only_controlled_incrementality_test"
        return "scale_only_on_positive_incremental_cash_cm3"

    @staticmethod
    def _inventory_action(decision: str, lifecycle: str) -> str:
        if decision == "blocked" or lifecycle == "exit":
            return "stop_replenishment_and_review_exit"
        if decision == "needs_category_data" or lifecycle == "research":
            return "no_inventory_commitment"
        if lifecycle in {"qualified", "pilot"}:
            return "jit_or_small_pilot_with_frozen_stop_loss"
        return "cash_constrained_replenishment_proposal"

    @staticmethod
    def _category_tree(
        profile: dict[str, Any] | None,
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if profile is None:
            return []
        result = []
        for path in profile.get("category_paths") or []:
            path_id = path["path_id"]
            routed = [
                item
                for item in candidates
                if (item.get("store_category_route") or {})
                .get("target_category_path", {})
                .get("path_id")
                == path_id
            ]
            result.append(
                {
                    **path,
                    "candidate_count": len(routed),
                    "candidate_ids": [item["candidate_id"] for item in routed],
                }
            )
        return result

    @staticmethod
    def _plan_snapshot(
        row: StoreOperatingPlanSnapshotRow, *, idempotent: bool
    ) -> dict[str, Any]:
        return {
            "contract_id": StoreCategoryStrategyWorkspace.PLAN_CONTRACT_ID,
            "snapshot_id": row.id,
            "profile_id": row.profile_id,
            "status": row.status,
            "scope": {
                "tenant_ref": row.tenant_ref,
                "entity_ref": row.entity_ref,
                "store_ref": row.store_ref,
                "scope_grant_authority_sha256": row.scope_grant_authority_sha256,
            },
            "as_of": row.as_of.isoformat(),
            "input_snapshot_sha256": row.input_snapshot_sha256,
            "output_snapshot_sha256": row.output_snapshot_sha256,
            "snapshot": row.snapshot_json,
            "evidence_ids": row.evidence_ids_json,
            "idempotent": idempotent,
            "external_write_allowed": False,
        }

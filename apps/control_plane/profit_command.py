from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .evidence import EvidenceGrade
from .market_recon_bundle import MarketReconBundleItemRow, MarketReconBundleRunRow
from .money import MoneyAmount
from .security import Principal
from .sql_repository import Base

COST_COMPONENTS = (
    "product_cost",
    "domestic_logistics",
    "international_logistics",
    "packaging",
    "warehousing",
    "customs",
    "tax",
    "last_mile",
    "platform_fee",
    "advertising",
    "return",
    "fx",
    "capital_cost",
    "customer_compensation",
    "damage",
)
ALGORITHM_VERSION = "kjds-profit-command-v1.0.0"


class ProfitCommandConflict(ValueError):
    pass


class ProfitDecisionSnapshotRow(Base):
    __tablename__ = "profit_decision_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "input_snapshot_sha256",
            name="uq_profit_decision_scope_input",
        ),
        CheckConstraint(
            "length(scope_grant_authority_sha256) = 64 "
            "AND length(input_snapshot_sha256) = 64 "
            "AND length(output_snapshot_sha256) = 64",
            name="ck_profit_decision_snapshot_hashes",
        ),
        CheckConstraint(
            "status IN ('ready_with_constraints','no_data','blocked')",
            name="ck_profit_decision_snapshot_status",
        ),
        Index(
            "ix_profit_decision_scope_created",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(180), primary_key=True)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    bundle_id: Mapped[str | None] = mapped_column(
        ForeignKey("market_recon_bundle_runs.id"), nullable=True
    )
    algorithm_version: Mapped[str] = mapped_column(String(100), nullable=False)
    display_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    input_snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    output_snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    evidence_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[str] = mapped_column(String(240), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProfitPilotProposalRow(Base):
    __tablename__ = "profit_pilot_proposals"
    __table_args__ = (
        UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "idempotency_key",
            name="uq_profit_pilot_scope_idempotency",
        ),
        CheckConstraint(
            "status IN ('proposal_only','blocked')",
            name="ck_profit_pilot_proposal_status",
        ),
        CheckConstraint(
            "length(request_sha256) = 64",
            name="ck_profit_pilot_proposal_hash",
        ),
        CheckConstraint(
            "external_write_allowed IS FALSE AND approval_created IS FALSE "
            "AND permit_created IS FALSE AND pilot_started IS FALSE",
            name="ck_profit_pilot_proposal_authority",
        ),
        Index(
            "ix_profit_pilot_scope_created",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(180), primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("profit_decision_snapshots.id"), nullable=False)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    candidate_id: Mapped[str] = mapped_column(String(240), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(180), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence_records.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    reason_codes_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    budget_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    budget_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    stop_loss_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    proposal_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    external_write_allowed: Mapped[bool] = mapped_column(nullable=False, default=False)
    approval_created: Mapped[bool] = mapped_column(nullable=False, default=False)
    permit_created: Mapped[bool] = mapped_column(nullable=False, default=False)
    pilot_started: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_by: Mapped[str] = mapped_column(String(240), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProfitCommandWorkspace:
    """Compose existing authorities into one profit-first decision surface."""

    CONTRACT_ID = "kjds-profit-command-workspace-v1"

    def __init__(
        self,
        *,
        engine,
        evidence,
        batch_opportunity=None,
        profit_ledger=None,
        settlement_cash=None,
        inventory=None,
        oms=None,
        sourcing=None,
        growth=None,
        store_strategy=None,
        data_remediation=None,
        store_profile_intake=None,
    ) -> None:
        self.engine = engine
        self.evidence = evidence
        self.batch_opportunity = batch_opportunity
        self.profit_ledger = profit_ledger
        self.settlement_cash = settlement_cash
        self.inventory = inventory
        self.oms = oms
        self.sourcing = sourcing
        self.growth = growth
        self.store_strategy = store_strategy
        self.data_remediation = data_remediation
        self.store_profile_intake = store_profile_intake

    def project(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        display_currency: str = "CNY",
    ) -> dict[str, Any]:
        scope = self._scope(principal, entity_scope, store_ref, as_of)
        display_currency = self._currency(display_currency)
        authorities = self._authority_projections(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
            display_currency=display_currency,
        )
        bundle, product_rows = self._latest_products(scope=scope, as_of=as_of)
        batch_by_offer = self._batch_by_offer(authorities["batch_opportunity"]["payload"])
        accrual_by_sku = self._accrual_by_sku(
            authorities["actual_profit"]["payload"],
            as_of=as_of,
        )
        candidates = [
            self._candidate(
                row,
                bundle_id=bundle.id if bundle else None,
                batch_candidate=batch_by_offer.get(str(row.payload_json.get("offer_id") or "")),
                accrual_profit=accrual_by_sku.get(str(row.payload_json.get("offer_id") or "")),
                display_currency=display_currency,
                as_of=as_of,
            )
            for row in product_rows
        ]
        store_profile = None
        if self.store_strategy is not None:
            store_profile = self.store_strategy.current_profile(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                as_of=as_of,
            )
            profile = store_profile.get("profile")
            candidates = [
                self.store_strategy.compile_candidate(candidate, profile=profile)
                for candidate in candidates
            ]
        status = "ready_with_constraints" if candidates else "no_data"
        decision_counts = {
            name: sum(candidate["decision_class"] == name for candidate in candidates)
            for name in ("stop_loss", "reprice", "pilot", "hold", "exit", "needs_data")
        }
        source_gaps = sorted(
            {
                *(("market_recon_bundle_missing",) if bundle is None else ()),
                *(
                    gap
                    for authority in authorities.values()
                    for gap in authority["source_gaps"]
                ),
                *(
                    reason
                    for candidate in candidates
                    for reason in candidate["reason_codes"]
                ),
            }
        )
        evidence_ids = sorted(
            {
                *((bundle.archive_evidence_id,) if bundle else ()),
                *(
                    evidence_id
                    for candidate in candidates
                    for evidence_id in candidate["evidence_ids"]
                ),
            }
        )
        input_core = {
            "algorithm_version": ALGORITHM_VERSION,
            "scope": scope,
            "as_of": as_of.astimezone(UTC).isoformat(),
            "display_currency": display_currency,
            "bundle_sha256": bundle.bundle_sha256 if bundle else None,
            "authority_snapshots": {
                name: value["snapshot_sha256"] for name, value in authorities.items()
            },
            "store_profile_sha256": (
                store_profile.get("profile_sha256") if store_profile else None
            ),
            "candidate_sources": [candidate["input_sha256"] for candidate in candidates],
        }
        payload = {
            "contract_id": self.CONTRACT_ID,
            "algorithm_version": ALGORITHM_VERSION,
            "status": status,
            "as_of": as_of.astimezone(UTC).isoformat(),
            "scope": scope,
            "display_currency": display_currency,
            "bundle": (
                {
                    "bundle_id": bundle.id,
                    "status": bundle.status,
                    "bundle_sha256": bundle.bundle_sha256,
                    "archive_evidence_id": bundle.archive_evidence_id,
                    "counts": {
                        "source_total": bundle.source_total,
                        "accepted": bundle.accepted_count,
                        "quarantined": bundle.quarantined_count,
                    },
                    "quality": bundle.quality_json,
                }
                if bundle
                else None
            ),
            "summary": {
                "actual_cash_profit": self._cash_summary(
                    authorities["settlement_cash"]["payload"], display_currency
                ),
                "risk_profit_opportunities": decision_counts["pilot"],
                "loss_exposure": {
                    "status": "no_data",
                    "amount": None,
                    "currency": display_currency,
                    "reason": "actual_cash_profit_not_reconciled_by_sku",
                },
                "inventory_cash": {
                    "status": authorities["inventory"]["status"],
                    "amount": None,
                    "currency": display_currency,
                    "reason": "inventory_cost_basis_not_reconciled",
                },
                "highest_value_action": self._highest_action(candidates),
                "data_freshness": {
                    "as_of": as_of.astimezone(UTC).isoformat(),
                    "bundle_available": bundle is not None,
                    "decision_eligible_records": (
                        bundle.quality_json.get("decision_eligible_records", 0) if bundle else 0
                    ),
                },
            },
            "counts": {
                "candidates": len(candidates),
                **decision_counts,
            },
            "candidates": candidates,
            "authority_status": {
                name: {
                    "status": value["status"],
                    "snapshot_sha256": value["snapshot_sha256"],
                    "source_gaps": value["source_gaps"],
                }
                for name, value in authorities.items()
            },
            "store_strategy_profile": (
                {
                    "status": store_profile.get("status"),
                    "profile_id": store_profile.get("profile_id"),
                    "profile_sha256": store_profile.get("profile_sha256"),
                    "reason_codes": store_profile.get("reason_codes", []),
                    "registry": store_profile.get("registry"),
                }
                if store_profile
                else {
                    "status": "unbound",
                    "profile_id": None,
                    "profile_sha256": None,
                    "reason_codes": ["store_category_strategy_unbound"],
                    "registry": None,
                }
            ),
            "source_gaps": source_gaps,
            "blockers": [self._blocker(code) for code in source_gaps],
            "evidence_ids": evidence_ids,
            "drillthrough": {
                "scope_path": "tenant/country/platform/store/category/spu/sku/order/fee/settlement/evidence",
                "bundle_quality": (
                    f"/v1/intelligence-ingestion/bundles/{bundle.id}/quality" if bundle else None
                ),
                "profit_ledger": "/v1/profit-ledger",
                "finance_control": "/v1/finance-control/workspace",
                "inventory": "/v1/inventory/workspace",
                "oms": "/v1/oms/workspace",
                "sourcing": "/v1/sourcing-intelligence/workspace",
                "growth": "/v1/growth-experiments/workspace",
            },
            "control_envelope": {
                "read_only": True,
                "formal_fact_promoted": False,
                "approval_created": False,
                "permit_created": False,
                "pilot_started": False,
                "automatic_reprice_allowed": False,
                "automatic_purchase_allowed": False,
                "automatic_advertising_allowed": False,
                "external_write_allowed": False,
            },
        }
        payload["input_snapshot_sha256"] = self._hash(input_core)
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def candidate(
        self,
        candidate_id: str,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        display_currency: str = "CNY",
    ) -> dict[str, Any]:
        workspace = self.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
            display_currency=display_currency,
        )
        matches = [item for item in workspace["candidates"] if item["candidate_id"] == candidate_id]
        if len(matches) != 1:
            raise KeyError("Profit candidate not found in the authorized scope")
        return {
            "contract_id": self.CONTRACT_ID,
            "status": workspace["status"],
            "scope": workspace["scope"],
            "as_of": workspace["as_of"],
            "display_currency": workspace["display_currency"],
            "candidate": matches[0],
            "input_snapshot_sha256": workspace["input_snapshot_sha256"],
            "snapshot_sha256": workspace["snapshot_sha256"],
            "control_envelope": workspace["control_envelope"],
        }

    def candidates(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        display_currency: str = "CNY",
        decision_class: str | None = None,
        lifecycle: str | None = None,
        category_id: str | None = None,
        query: str | None = None,
        page_size: int = 50,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        if not 1 <= page_size <= 200:
            raise ValueError("page_size must be between 1 and 200")
        allowed_decisions = {
            "stop_loss",
            "reprice",
            "pilot",
            "hold",
            "exit",
            "needs_data",
        }
        allowed_lifecycles = {
            "research",
            "qualified",
            "pilot",
            "incubation",
            "growth",
            "proven",
            "defend",
            "harvest",
            "exit",
        }
        if decision_class not in {None, *allowed_decisions}:
            raise ValueError("decision_class filter is invalid")
        if lifecycle not in {None, *allowed_lifecycles}:
            raise ValueError("lifecycle filter is invalid")
        workspace = self.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
            display_currency=display_currency,
        )
        normalized_query = str(query or "").strip().casefold()
        normalized_category = str(category_id or "").strip()
        rows = sorted(workspace["candidates"], key=lambda item: item["candidate_id"])
        rows = [
            item
            for item in rows
            if (
                decision_class is None
                or item.get("decision_class") == decision_class
            )
            and (
                lifecycle is None
                or ((item.get("store_category_route") or {}).get("playbook") or {}).get(
                    "lifecycle"
                )
                == lifecycle
            )
            and (
                not normalized_category
                or normalized_category
                in {
                    str((item.get("category_identity") or {}).get("source_category_id") or ""),
                    str((item.get("category_identity") or {}).get("product_type_id") or ""),
                }
            )
            and (
                not normalized_query
                or normalized_query in str(item.get("offer_id") or "").casefold()
                or normalized_query in str(item.get("name") or "").casefold()
            )
        ]
        if cursor:
            rows = [item for item in rows if item["candidate_id"] > cursor]
        page = rows[:page_size]
        next_cursor = page[-1]["candidate_id"] if len(rows) > page_size else None
        payload = {
            "contract_id": "kjds-profit-command-candidate-collection-v1",
            "status": workspace["status"],
            "scope": workspace["scope"],
            "as_of": workspace["as_of"],
            "display_currency": workspace["display_currency"],
            "filters": {
                "decision_class": decision_class,
                "lifecycle": lifecycle,
                "category_id": category_id,
                "query": query,
            },
            "pagination": {
                "page_size": page_size,
                "next_cursor": next_cursor,
            },
            "count": len(page),
            "candidates": page,
            "source_snapshot_sha256": workspace["snapshot_sha256"],
            "control_envelope": workspace["control_envelope"],
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def remediation(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        display_currency: str = "CNY",
        queue_page_size: int | None = None,
        queue_offset: int = 0,
    ) -> dict[str, Any]:
        if queue_page_size is not None and not 1 <= queue_page_size <= 200:
            raise ValueError("queue_page_size must be between 1 and 200")
        if queue_offset < 0:
            raise ValueError("queue_offset cannot be negative")
        scope = self._scope(principal, entity_scope, store_ref, as_of)
        if self.data_remediation is None:
            raise RuntimeError("Profit data remediation is not configured")
        candidate_workspace = self.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
            display_currency=display_currency,
        )
        with Session(self.engine) as session:
            bundle = session.scalar(
                select(MarketReconBundleRunRow)
                .where(
                    MarketReconBundleRunRow.tenant_ref == scope["tenant_ref"],
                    MarketReconBundleRunRow.entity_ref == scope["entity_ref"],
                    MarketReconBundleRunRow.store_ref == scope["store_ref"],
                    MarketReconBundleRunRow.as_of <= as_of,
                )
                .order_by(
                    MarketReconBundleRunRow.as_of.desc(),
                    MarketReconBundleRunRow.created_at.desc(),
                    MarketReconBundleRunRow.id.desc(),
                )
            )
            if bundle is None:
                payload = {
                    "contract_id": self.data_remediation.CONTRACT_ID,
                    "workspace_id": None,
                    "input_sha256": None,
                    "scope": scope,
                    "as_of": as_of.astimezone(UTC).isoformat(),
                    "status": "no_data",
                    "reconciliation": {
                        "source_total": None,
                        "accepted": None,
                        "quarantined": None,
                        "conservation_passed": None,
                        "all_source_items_retained": None,
                    },
                    "summary": {
                        "source_items": 0,
                        "candidates": len(candidate_workspace["candidates"]),
                        "remediation_items": 0,
                        "open": 0,
                        "stale": 0,
                        "blocked": 0,
                    },
                    "source_inventory": [],
                    "candidate_inventory": [],
                    "remediation_queue": [],
                    "groups": {
                        "by_sku": [],
                        "by_source": [],
                        "by_error_code": [],
                        "by_evidence_requirement": [],
                    },
                    "source_gaps": ["market_recon_bundle_missing"],
                    "control_envelope": {
                        "missing_values_guessed": False,
                        "formal_fact_promoted": False,
                        "automatic_action_allowed": False,
                        "external_write_allowed": False,
                        "cross_currency_aggregation_performed": False,
                        "cross_currency_value_comparison_performed": False,
                        "source_history_rewritten": False,
                    },
                }
                payload["snapshot_sha256"] = self._hash(payload)
                if queue_page_size is not None:
                    payload["source_snapshot_sha256"] = payload["snapshot_sha256"]
                    payload["pagination"] = {
                        "page_size": queue_page_size,
                        "offset": queue_offset,
                        "previous_offset": None,
                        "next_offset": None,
                        "page_count": 0,
                        "total_count": 0,
                    }
                    payload["snapshot_sha256"] = self._hash(payload)
                return payload
            source_items = session.scalars(
                select(MarketReconBundleItemRow)
                .where(
                    MarketReconBundleItemRow.bundle_id == bundle.id,
                    MarketReconBundleItemRow.tenant_ref == scope["tenant_ref"],
                    MarketReconBundleItemRow.entity_ref == scope["entity_ref"],
                    MarketReconBundleItemRow.store_ref == scope["store_ref"],
                )
                .order_by(
                    MarketReconBundleItemRow.artifact_kind,
                    MarketReconBundleItemRow.record_index,
                    MarketReconBundleItemRow.id,
                )
            ).all()
            source_scope = {
                "tenant_ref": bundle.tenant_ref,
                "entity_ref": bundle.entity_ref,
                "store_ref": bundle.store_ref,
                "scope_grant_authority_sha256": bundle.scope_grant_authority_sha256,
            }
            result = self.data_remediation.project(
                scope=source_scope,
                bundle=bundle,
                source_items=source_items,
                candidates={**candidate_workspace, "scope": source_scope},
                as_of=as_of,
            )
        result["access_authority"] = {
            "current_scope_grant_authority_sha256": scope[
                "scope_grant_authority_sha256"
            ],
            "source_scope_grant_authority_sha256": source_scope[
                "scope_grant_authority_sha256"
            ],
            "grant_rotated": scope["scope_grant_authority_sha256"]
            != source_scope["scope_grant_authority_sha256"],
        }
        result["drillthrough"] = {
            "bundle_quality": f"/v1/intelligence-ingestion/bundles/{bundle.id}/quality",
            "profit_candidates": "/v1/profit-command/candidates",
            "finance_control": "/v1/finance-control/workspace",
            "sourcing": "/v1/sourcing-intelligence/workspace",
            "evidence_graph": "/v1/profit-command/lineage",
        }
        result["snapshot_sha256"] = self._hash(result)
        if queue_page_size is not None:
            full_queue = result["remediation_queue"]
            result["source_snapshot_sha256"] = result["snapshot_sha256"]
            result["remediation_queue"] = full_queue[
                queue_offset : queue_offset + queue_page_size
            ]
            next_offset = (
                queue_offset + queue_page_size
                if queue_offset + queue_page_size < len(full_queue)
                else None
            )
            result["pagination"] = {
                "page_size": queue_page_size,
                "offset": queue_offset,
                "previous_offset": max(0, queue_offset - queue_page_size)
                if queue_offset
                else None,
                "next_offset": next_offset,
                "page_count": len(result["remediation_queue"]),
                "total_count": len(full_queue),
            }
            result["snapshot_sha256"] = self._hash(result)
        return result

    def store_profile_proposal(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        seller_tier: str,
        as_of: datetime,
        display_currency: str = "CNY",
        destination_profiles: tuple[dict[str, Any], ...] = (),
    ) -> dict[str, Any]:
        if self.store_profile_intake is None:
            raise RuntimeError("Store profile intake is not configured")
        workspace = self.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
            display_currency=display_currency,
        )
        observations: list[dict[str, Any]] = []
        scope = workspace["scope"]
        for candidate in workspace["candidates"]:
            category = candidate.get("category_identity") or {}
            category_id = str(category.get("source_category_id") or "").strip()
            evidence_ids = [
                str(item).strip()
                for item in candidate.get("evidence_ids") or []
                if str(item).strip()
            ]
            own_price = (candidate.get("raw_money") or {}).get("own_price") or {}
            observed_at = own_price.get("occurred_at") or workspace["as_of"]
            if not category_id or not evidence_ids:
                continue
            common = {
                "evidence_refs": evidence_ids,
                "observed_at": observed_at,
                "scope": {
                    "tenant_ref": scope["tenant_ref"],
                    "entity_ref": scope["entity_ref"],
                    "store_ref": scope["store_ref"],
                },
                "data_grade": "B",
                "confidence": "0.85",
                "identity_quality": "exact",
                "variant_quality": "ambiguous",
                "category": {
                    "category_id": category_id,
                    "category_name": category_id,
                    "kind": "official",
                    "ancestry": [],
                },
            }
            observations.append(
                {
                    **common,
                    "evidence_type": "listing",
                    "metrics": {"listing_count": "1"},
                }
            )
            observations.append(
                {
                    **common,
                    "evidence_type": "category",
                    "metrics": {},
                }
            )
        proposal = self.store_profile_intake.propose(
            observations,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            seller_tier=seller_tier,
            as_of=as_of,
            destination_profiles=destination_profiles,
        ).to_dict()
        proposal["source_workspace_sha256"] = workspace["snapshot_sha256"]
        proposal["source_observation_count"] = len(observations)
        proposal["source_gaps"] = sorted(
            {
                *proposal.get("reason_codes", []),
                *(
                    ["exact_variant_identity_missing"]
                    if observations
                    else ["category_listing_evidence_missing"]
                ),
            }
        )
        proposal["snapshot_sha256"] = self._hash(proposal)
        return proposal

    def analytics(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        display_currency: str = "CNY",
    ) -> dict[str, Any]:
        workspace = self.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
            display_currency=display_currency,
        )
        candidates = workspace["candidates"]
        decision_distribution = self._distribution(
            candidates, lambda item: str(item.get("decision_class") or "no_data")
        )
        lifecycle_distribution = self._distribution(
            candidates,
            lambda item: str(
                ((item.get("store_category_route") or {}).get("playbook") or {}).get(
                    "lifecycle"
                )
                or "no_data"
            ),
        )
        route_distribution = self._distribution(
            candidates,
            lambda item: str(
                (item.get("store_category_route") or {}).get("decision")
                or "unbound"
            ),
        )
        basis_coverage = {
            basis: self._distribution(
                candidates,
                lambda item, basis=basis: str(
                    ((item.get("profit") or {}).get(basis) or {}).get("status")
                    or "no_data"
                ),
            )
            for basis in (
                "scenario_profit",
                "accrual_profit",
                "settlement_profit",
                "cash_profit",
                "risk_adjusted_profit",
            )
        }
        cost_matrix = {
            component: self._distribution(
                candidates,
                lambda item, component=component: next(
                    (
                        str(row.get("status") or "unknown")
                        for row in (item.get("cost_coverage") or {}).get("components", [])
                        if row.get("name") == component
                    ),
                    "unknown",
                ),
            )
            for component in COST_COMPONENTS
        }
        categories: dict[tuple[str, str], dict[str, Any]] = {}
        for item in candidates:
            identity = item.get("category_identity") or {}
            key = (
                str(identity.get("source_category_id") or "no_data"),
                str(identity.get("product_type_id") or "no_data"),
            )
            row = categories.setdefault(
                key,
                {
                    "source_category_id": key[0],
                    "product_type_id": key[1],
                    "candidate_count": 0,
                    "decision_counts": {},
                    "route_counts": {},
                },
            )
            row["candidate_count"] += 1
            decision = str(item.get("decision_class") or "no_data")
            route = str(
                (item.get("store_category_route") or {}).get("decision")
                or "unbound"
            )
            row["decision_counts"][decision] = row["decision_counts"].get(decision, 0) + 1
            row["route_counts"][route] = row["route_counts"].get(route, 0) + 1
        metrics = {
            "scenario_baseline_cm3": self._aggregate_profit_metric(
                candidates, "scenario_profit", "baseline_cm3"
            ),
            "scenario_expected_cm3": self._aggregate_profit_metric(
                candidates, "scenario_profit", "expected_cm3"
            ),
            "scenario_downside_cm3": self._aggregate_profit_metric(
                candidates, "scenario_profit", "downside_cm3"
            ),
            "scenario_cvar_cm3": self._aggregate_profit_metric(
                candidates, "scenario_profit", "cvar_cm3"
            ),
            "accrual_profit": self._aggregate_profit_metric(
                candidates, "accrual_profit", "amount"
            ),
            "settlement_profit": self._aggregate_profit_metric(
                candidates, "settlement_profit", "amount"
            ),
            "cash_profit": self._aggregate_profit_metric(
                candidates, "cash_profit", "amount"
            ),
            "risk_downside_cm3": self._aggregate_profit_metric(
                candidates, "risk_adjusted_profit", "downside_cm3"
            ),
        }
        payload = {
            "contract_id": "kjds-profit-command-analytics-v1",
            "status": workspace["status"],
            "scope": workspace["scope"],
            "as_of": workspace["as_of"],
            "display_currency": workspace["display_currency"],
            "summary": workspace["summary"],
            "counts": workspace["counts"],
            "decision_distribution": decision_distribution,
            "lifecycle_distribution": lifecycle_distribution,
            "route_distribution": route_distribution,
            "profit_basis_coverage": basis_coverage,
            "profit_metrics": metrics,
            "cost_state_matrix": cost_matrix,
            "category_matrix": sorted(
                categories.values(),
                key=lambda item: (
                    item["source_category_id"],
                    item["product_type_id"],
                ),
            ),
            "time_series": {
                "status": "no_data",
                "points": [],
                "reason": "replayable_profit_time_series_missing",
                "synthetic_points_created": False,
            },
            "source_snapshot_sha256": workspace["snapshot_sha256"],
            "control_envelope": {
                **workspace["control_envelope"],
                "client_profit_recalculation": False,
                "synthetic_business_data_allowed": False,
            },
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def lineage(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        display_currency: str = "CNY",
        candidate_id: str | None = None,
    ) -> dict[str, Any]:
        workspace = self.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
            display_currency=display_currency,
        )
        candidates = workspace["candidates"]
        if candidate_id is not None:
            candidates = [
                item for item in candidates if item["candidate_id"] == candidate_id
            ]
            if not candidates:
                raise KeyError("Profit candidate not found in the authorized scope")
        bundle = workspace.get("bundle") or {}
        stage_order = (
            "raw_evidence",
            "normalized_observation",
            "reviewed_observation",
            "formal_fact",
            "decision_snapshot",
        )
        stage_counts = (bundle.get("quality") or {}).get("stage_counts") or {}
        nodes = [
            {
                "id": stage,
                "stage": stage,
                "count": int(stage_counts.get(stage, 0)),
                "status": "available" if int(stage_counts.get(stage, 0)) else "no_data",
            }
            for stage in stage_order
        ]
        edges = [
            {
                "source": stage_order[index],
                "target": stage_order[index + 1],
                "automatic_promotion": False,
            }
            for index in range(len(stage_order) - 1)
        ]
        payload = {
            "contract_id": "kjds-profit-command-lineage-v1",
            "status": workspace["status"],
            "scope": workspace["scope"],
            "as_of": workspace["as_of"],
            "candidate_id": candidate_id,
            "bundle": bundle,
            "nodes": nodes,
            "edges": edges,
            "candidate_lineage": [
                {
                    "candidate_id": item["candidate_id"],
                    "offer_id": item.get("offer_id"),
                    "data_stage": (item.get("quality") or {}).get("data_stage"),
                    "category_identity": item.get("category_identity"),
                    "store_category_route": item.get("store_category_route"),
                    "evidence_ids": item.get("evidence_ids") or [],
                    "input_sha256": item.get("input_sha256"),
                    "drillthrough": item.get("drillthrough"),
                }
                for item in candidates
            ],
            "quarantine": {
                "count": (bundle.get("counts") or {}).get("quarantined", 0),
                "quality_endpoint": (workspace.get("drillthrough") or {}).get(
                    "bundle_quality"
                ),
                "raw_data_deleted": False,
            },
            "source_snapshot_sha256": workspace["snapshot_sha256"],
            "control_envelope": {
                **workspace["control_envelope"],
                "automatic_fact_promotion": False,
            },
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    @classmethod
    def portfolio(
        cls,
        workspaces: list[dict[str, Any]],
        *,
        tenant_ref: str,
        as_of: datetime,
        display_currency: str,
        store_coverage: list[dict[str, Any]],
    ) -> dict[str, Any]:
        cutoff = as_of.astimezone(UTC)
        decision_names = (
            "stop_loss",
            "reprice",
            "pilot",
            "hold",
            "exit",
            "needs_data",
        )
        decision_counts = {
            name: sum(
                int((workspace.get("counts") or {}).get(name, 0))
                for workspace in workspaces
            )
            for name in decision_names
        }
        payload = {
            "contract_id": "kjds-profit-command-portfolio-v1",
            "status": "ready_with_constraints" if workspaces else "no_data",
            "tenant_ref": tenant_ref,
            "as_of": cutoff.isoformat(),
            "display_currency": display_currency,
            "store_coverage": store_coverage,
            "summary": {
                "store_count": len(workspaces),
                "candidate_count": sum(
                    int((workspace.get("counts") or {}).get("candidates", 0))
                    for workspace in workspaces
                ),
                "decision_counts": decision_counts,
                "actual_cash_profit": {
                    "status": "available_by_store_not_aggregated",
                    "amount": None,
                    "currency": display_currency,
                    "stores": [
                        {
                            "store_ref": (workspace.get("scope") or {}).get("store_ref"),
                            "metric": (workspace.get("summary") or {}).get(
                                "actual_cash_profit"
                            ),
                        }
                        for workspace in workspaces
                    ],
                    "reason": "aggregate_money_evidence_snapshot_required",
                },
            },
            "stores": [
                {
                    "scope": workspace.get("scope"),
                    "status": workspace.get("status"),
                    "summary": workspace.get("summary"),
                    "counts": workspace.get("counts"),
                    "store_strategy_profile": workspace.get("store_strategy_profile"),
                    "snapshot_sha256": workspace.get("snapshot_sha256"),
                }
                for workspace in workspaces
            ],
            "control_envelope": {
                "read_only": True,
                "cross_store_amount_aggregation": False,
                "client_profit_recalculation": False,
                "synthetic_business_data_allowed": False,
                "external_write_allowed": False,
            },
        }
        payload["snapshot_sha256"] = cls._hash(payload)
        return payload

    def propose_pilot(
        self,
        candidate_id: str,
        *,
        request: dict[str, Any],
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        display_currency: str = "CNY",
    ) -> dict[str, Any]:
        scope = self._scope(principal, entity_scope, store_ref, as_of)
        display_currency = self._currency(display_currency)
        idempotency_key = self._required(request.get("idempotency_key"), "idempotency_key", 180)
        budget = self._optional_positive_decimal(request.get("max_budget_amount"), "max_budget_amount")
        stop_loss = self._optional_positive_decimal(request.get("stop_loss_amount"), "stop_loss_amount")
        request_core = {
            "contract_id": "kjds-profit-pilot-proposal-request-v1",
            "scope": scope,
            "candidate_id": candidate_id,
            "idempotency_key": idempotency_key,
            "display_currency": display_currency,
            "max_budget_amount": self._decimal_text(budget),
            "stop_loss_amount": self._decimal_text(stop_loss),
        }
        request_sha256 = self._hash(request_core)
        with Session(self.engine) as session:
            existing = session.scalar(
                select(ProfitPilotProposalRow).where(
                    ProfitPilotProposalRow.tenant_ref == scope["tenant_ref"],
                    ProfitPilotProposalRow.entity_ref == scope["entity_ref"],
                    ProfitPilotProposalRow.store_ref == scope["store_ref"],
                    ProfitPilotProposalRow.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                if existing.request_sha256 != request_sha256:
                    raise ProfitCommandConflict(
                        "Pilot proposal idempotency key already has different immutable content"
                    )
                return self._proposal_projection(existing, idempotent=True)

        workspace = self.project(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
            display_currency=display_currency,
        )
        candidates = [item for item in workspace["candidates"] if item["candidate_id"] == candidate_id]
        if len(candidates) != 1:
            raise KeyError("Profit candidate not found in the authorized scope")
        candidate = candidates[0]
        reasons = list(candidate["reason_codes"])
        downside = self._optional_decimal(
            candidate["profit"]["risk_adjusted_profit"].get("downside_cm3"),
            "downside_cm3",
        )
        if candidate["decision_class"] != "pilot" or downside is None or downside <= 0:
            reasons.append("positive_downside_cm3_missing")
        if budget is None:
            reasons.append("pilot_budget_missing")
        if stop_loss is None:
            reasons.append("pilot_stop_loss_missing")
        status = "proposal_only" if not reasons else "blocked"
        now = datetime.now(UTC)
        with Session(self.engine) as session, session.begin():
            request_evidence = self.evidence.capture(
                content=self._canonical(request_core),
                filename=f"pilot-proposal-request-{request_sha256[:16]}.json",
                content_type="application/json",
                source="profit-pilot-proposal-request",
                source_ref=(
                    f"profit-pilot-proposal://{scope['tenant_ref']}/{scope['entity_ref']}/"
                    f"{scope['store_ref']}/{idempotency_key}"
                ),
                grade=EvidenceGrade.B,
                effective_at=as_of.isoformat(),
                effective_until=None,
                created_by=principal.actor_id,
                metadata={
                    **scope,
                    "contract_id": request_core["contract_id"],
                    "request_sha256": request_sha256,
                    "retention_class": "experiment",
                    "formal_fact": False,
                    "external_write_allowed": False,
                },
                _session=session,
            )
            snapshot = self._persist_snapshot(
                session,
                workspace=workspace,
                principal=principal,
                as_of=as_of,
            )
            budget_money = (
                MoneyAmount(budget, display_currency, as_of, request_evidence.id).to_dict()
                if budget is not None
                else None
            )
            stop_loss_money = (
                MoneyAmount(stop_loss, display_currency, as_of, request_evidence.id).to_dict()
                if stop_loss is not None
                else None
            )
            proposal = {
                "contract_id": "kjds-profit-pilot-proposal-v1",
                "candidate_id": candidate_id,
                "status": status,
                "decision_snapshot_id": snapshot.id,
                "request_evidence_id": request_evidence.id,
                "downside_cm3": self._decimal_text(downside),
                "budget_limit": budget_money,
                "stop_loss_limit": stop_loss_money,
                "reason_codes": sorted(set(reasons)),
                "next_action": (
                    "Submit the frozen proposal for independent approval."
                    if status == "proposal_only"
                    else "Resolve every evidence, economics, budget, and stop-loss blocker before a Pilot proposal."
                ),
                "proposal_only": True,
                "formal_fact": False,
                "approval_created": False,
                "permit_created": False,
                "pilot_started": False,
                "external_write_allowed": False,
            }
            row = ProfitPilotProposalRow(
                id=new_id("ppp"),
                snapshot_id=snapshot.id,
                tenant_ref=scope["tenant_ref"],
                entity_ref=scope["entity_ref"],
                store_ref=scope["store_ref"],
                candidate_id=candidate_id,
                idempotency_key=idempotency_key,
                request_sha256=request_sha256,
                request_evidence_id=request_evidence.id,
                status=status,
                reason_codes_json=proposal["reason_codes"],
                budget_amount=budget,
                budget_currency=display_currency if budget is not None else None,
                stop_loss_amount=stop_loss,
                proposal_json=proposal,
                external_write_allowed=False,
                approval_created=False,
                permit_created=False,
                pilot_started=False,
                created_by=principal.actor_id,
                created_at=now,
            )
            session.add(row)
            session.flush()
            return self._proposal_projection(row, idempotent=False)

    def _persist_snapshot(
        self,
        session: Session,
        *,
        workspace: dict[str, Any],
        principal: Principal,
        as_of: datetime,
    ) -> ProfitDecisionSnapshotRow:
        scope = workspace["scope"]
        input_sha = workspace["input_snapshot_sha256"]
        output_sha = workspace["snapshot_sha256"]
        existing = session.scalar(
            select(ProfitDecisionSnapshotRow).where(
                ProfitDecisionSnapshotRow.tenant_ref == scope["tenant_ref"],
                ProfitDecisionSnapshotRow.entity_ref == scope["entity_ref"],
                ProfitDecisionSnapshotRow.store_ref == scope["store_ref"],
                ProfitDecisionSnapshotRow.input_snapshot_sha256 == input_sha,
            )
        )
        if existing is not None:
            if existing.output_snapshot_sha256 != output_sha:
                raise ProfitCommandConflict("Decision snapshot input has non-deterministic output drift")
            return existing
        row = ProfitDecisionSnapshotRow(
            id=new_id("pds"),
            tenant_ref=scope["tenant_ref"],
            entity_ref=scope["entity_ref"],
            store_ref=scope["store_ref"],
            scope_grant_authority_sha256=scope["scope_grant_authority_sha256"],
            bundle_id=workspace["bundle"]["bundle_id"] if workspace["bundle"] else None,
            algorithm_version=workspace["algorithm_version"],
            display_currency=workspace["display_currency"],
            status=workspace["status"],
            input_snapshot_sha256=input_sha,
            output_snapshot_sha256=output_sha,
            snapshot_json=workspace,
            evidence_ids_json=workspace["evidence_ids"],
            as_of=as_of.astimezone(UTC),
            expires_at=as_of.astimezone(UTC) + timedelta(hours=24),
            created_by=principal.actor_id,
            created_at=datetime.now(UTC),
        )
        session.add(row)
        session.flush()
        return row

    def _authority_projections(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        display_currency: str,
    ) -> dict[str, dict[str, Any]]:
        calls: dict[str, Callable[[], dict[str, Any]] | None] = {
            "batch_opportunity": (
                lambda: self.batch_opportunity.latest(
                    principal=principal,
                    entity_scope=entity_scope,
                    store_ref=store_ref,
                    as_of=as_of,
                )
            ) if self.batch_opportunity is not None else None,
            "actual_profit": (
                lambda: self.profit_ledger.snapshot(
                    principal=principal,
                    entity_scope=entity_scope,
                    store_ref=store_ref,
                    as_of=as_of.isoformat(),
                    currency=display_currency,
                    grain="sku",
                    page_size=500,
                )
            ) if self.profit_ledger is not None else None,
            "settlement_cash": (
                lambda: self.settlement_cash.project(
                    principal=principal,
                    entity_scope=entity_scope,
                    store_ref=store_ref,
                    as_of=as_of.isoformat(),
                    page_size=100,
                )
            ) if self.settlement_cash is not None else None,
            "inventory": (
                lambda: self.inventory.workspace(
                    principal=principal,
                    entity_scope=entity_scope,
                    store_ref=store_ref,
                    as_of=as_of,
                    page_size=500,
                )
            ) if self.inventory is not None else None,
            "oms": (
                lambda: self.oms.workspace(
                    principal=principal,
                    entity_scope=entity_scope,
                    store_ref=store_ref,
                    as_of=as_of,
                    page_size=500,
                )
            ) if self.oms is not None else None,
            "sourcing": (
                lambda: self.sourcing.project(
                    principal=principal,
                    entity_scope=entity_scope,
                    store_ref=store_ref,
                    as_of=as_of,
                    display_currency=display_currency,
                    page_size=200,
                )
            ) if self.sourcing is not None else None,
            "growth": (
                lambda: self.growth.project(
                    principal=principal,
                    entity_scope=entity_scope,
                    store_ref=store_ref,
                    as_of=as_of,
                    page_size=100,
                )
            ) if self.growth is not None else None,
        }
        return {name: self._safe_authority(name, call) for name, call in calls.items()}

    @classmethod
    def _safe_authority(
        cls,
        name: str,
        call: Callable[[], dict[str, Any]] | None,
    ) -> dict[str, Any]:
        if call is None:
            return {
                "status": "no_data",
                "snapshot_sha256": None,
                "source_gaps": [f"{name}_authority_not_composed"],
                "payload": {},
            }
        try:
            payload = call()
        except (KeyError, RuntimeError, ValueError) as exc:
            return {
                "status": "blocked",
                "snapshot_sha256": None,
                "source_gaps": [f"{name}_projection_failed:{type(exc).__name__}"],
                "payload": {},
            }
        return {
            "status": str(payload.get("status") or "no_data"),
            "snapshot_sha256": (
                payload.get("snapshot_sha256")
                or payload.get("scoped_snapshot_sha256")
                or payload.get("source_snapshot_sha256")
            ),
            "source_gaps": sorted(set(payload.get("source_gaps") or [])),
            "payload": payload,
        }

    def _latest_products(
        self,
        *,
        scope: dict[str, str],
        as_of: datetime,
    ) -> tuple[MarketReconBundleRunRow | None, list[MarketReconBundleItemRow]]:
        with Session(self.engine) as session:
            bundle = session.scalar(
                select(MarketReconBundleRunRow)
                .where(
                    MarketReconBundleRunRow.tenant_ref == scope["tenant_ref"],
                    MarketReconBundleRunRow.entity_ref == scope["entity_ref"],
                    MarketReconBundleRunRow.store_ref == scope["store_ref"],
                    MarketReconBundleRunRow.as_of <= as_of,
                )
                .order_by(MarketReconBundleRunRow.as_of.desc(), MarketReconBundleRunRow.id.desc())
                .limit(1)
            )
            if bundle is None:
                return None, []
            rows = list(
                session.scalars(
                    select(MarketReconBundleItemRow)
                    .where(
                        MarketReconBundleItemRow.bundle_id == bundle.id,
                        MarketReconBundleItemRow.tenant_ref == scope["tenant_ref"],
                        MarketReconBundleItemRow.entity_ref == scope["entity_ref"],
                        MarketReconBundleItemRow.store_ref == scope["store_ref"],
                        MarketReconBundleItemRow.artifact_kind == "ozon_product_info",
                        MarketReconBundleItemRow.disposition == "accepted",
                    )
                    .order_by(MarketReconBundleItemRow.record_key)
                )
            )
            session.expunge(bundle)
            for row in rows:
                session.expunge(row)
            return bundle, rows

    def _candidate(
        self,
        row: MarketReconBundleItemRow,
        *,
        bundle_id: str | None,
        batch_candidate: dict[str, Any] | None,
        accrual_profit: dict[str, Any] | None,
        display_currency: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        payload = row.payload_json
        offer_id = str(payload.get("offer_id") or row.record_key)
        occurred_at = self._timestamp(payload.get("updated_at"), fallback=as_of)
        own_price = self._money(
            payload.get("price"),
            payload.get("currency_code"),
            occurred_at,
            row.artifact_evidence_id,
        )
        market_source = (payload.get("price_indexes") or {}).get("ozon_index_data") or {}
        market_price = self._money(
            market_source.get("minimal_price"),
            market_source.get("minimal_price_currency"),
            occurred_at,
            row.artifact_evidence_id,
        )
        reasons = ["fifteen_component_cost_evidence_incomplete", "settlement_profit_missing", "cash_profit_missing"]
        if own_price is None:
            reasons.append("own_price_currency_missing")
        if market_price is None:
            reasons.append("market_reference_price_missing")
        if own_price and market_price and own_price["currency"] != market_price["currency"]:
            reasons.append("fx_basis_missing")
        downside = None
        expected = None
        baseline = None
        cvar = None
        batch_evidence: list[str] = []
        pilot_basis = False
        if batch_candidate:
            economics = batch_candidate.get("economics") or {}
            downside = self._nested(economics, "downside", "cm3_cny")
            expected = self._nested(economics, "expected", "cm3_cny")
            baseline = self._nested(economics, "baseline", "cm3_cny")
            cvar = economics.get("cvar_cm3_cny")
            batch_evidence = [str(item) for item in batch_candidate.get("evidence_ids") or [] if str(item)]
            parsed_downside = self._optional_decimal(downside, "downside_cm3")
            pilot_basis = bool(batch_candidate.get("eligible_for_approval")) and parsed_downside is not None and parsed_downside > 0
            if pilot_basis:
                reasons = [
                    reason
                    for reason in reasons
                    if reason != "fifteen_component_cost_evidence_incomplete"
                ]
        decision_class = "pilot" if pilot_basis and not reasons else "needs_data"
        evidence_ids = sorted({row.artifact_evidence_id, *batch_evidence})
        input_sha = self._hash(
            {
                "bundle_id": bundle_id,
                "source_sha256": row.source_sha256,
                "batch_fingerprint": batch_candidate.get("fingerprint") if batch_candidate else None,
                "accrual": accrual_profit,
                "display_currency": display_currency,
            }
        )
        return {
            "candidate_id": f"ozon:{offer_id}",
            "offer_id": offer_id,
            "name": payload.get("name") or "",
            "category_identity": {
                "source_category_id": (
                    str(payload.get("description_category_id"))
                    if payload.get("description_category_id") not in (None, "")
                    else None
                ),
                "product_type_id": (
                    str(payload.get("type_id"))
                    if payload.get("type_id") not in (None, "")
                    else None
                ),
                "hierarchy": {
                    "level_1_id": None,
                    "level_2_id": None,
                    "level_3_id": None,
                },
                "hierarchy_status": "source_leaf_and_product_type_only",
                "derived_tags": [],
                "derived_tags_are_official_taxonomy": False,
            },
            "decision_class": decision_class,
            "decision_eligible": decision_class == "pilot",
            "raw_money": {
                "own_price": own_price,
                "market_reference_price": market_price,
                "display_currency": display_currency,
                "fx_basis": None,
            },
            "cost_coverage": {
                "required": len(COST_COMPONENTS),
                "evidenced": len(COST_COMPONENTS) if pilot_basis else 0,
                "estimated": 0,
                "unknown": 0 if pilot_basis else len(COST_COMPONENTS),
                "components": [
                    {
                        "name": component,
                        "status": "evidenced" if pilot_basis else "unknown",
                    }
                    for component in COST_COMPONENTS
                ],
            },
            "profit": {
                "scenario_profit": {
                    "status": "available" if downside is not None else "no_data",
                    "currency": "CNY" if downside is not None else None,
                    "baseline_cm3": baseline,
                    "expected_cm3": expected,
                    "downside_cm3": downside,
                    "cvar_cm3": cvar,
                    "authority": "batch_opportunity" if downside is not None else None,
                },
                "accrual_profit": accrual_profit or {
                    "status": "no_data",
                    "amount": None,
                    "currency": None,
                    "reason": "reconciled_accrual_profit_missing",
                },
                "settlement_profit": {
                    "status": "no_data",
                    "amount": None,
                    "currency": None,
                    "reason": "three_book_settlement_not_bound_to_sku",
                },
                "cash_profit": {
                    "status": "no_data",
                    "amount": None,
                    "currency": None,
                    "reason": "bank_cash_profit_not_bound_to_sku",
                },
                "risk_adjusted_profit": {
                    "status": "available" if downside is not None else "no_data",
                    "downside_cm3": downside,
                    "currency": "CNY" if downside is not None else None,
                },
            },
            "quality": {
                "data_stage": row.highest_stage,
                "identity_match": "offer_id_exact",
                "price_confidence": "source_currency_explicit" if own_price else "unknown",
                "quantity_confidence": "unknown",
                "variant_confidence": "unresolved",
            },
            "reason_codes": sorted(set(reasons)),
            "next_action": (
                "Freeze budget and stop-loss limits for an independently approved small Pilot."
                if decision_class == "pilot"
                else "Add evidenced FX, exact supplier variant, fifteen costs, settlement, and bank cash lineage."
            ),
            "owner": "profit-operations",
            "budget_limit": None,
            "stop_loss_condition": None,
            "evidence_ids": evidence_ids,
            "drillthrough": {
                "candidate": f"/v1/profit-command/candidates/ozon:{offer_id}",
                "bundle_quality": (
                    f"/v1/intelligence-ingestion/bundles/{bundle_id}/quality" if bundle_id else None
                ),
                "source_evidence": f"/v1/evidence/{row.artifact_evidence_id}",
                "orders": f"/v1/oms/workspace?query={offer_id}",
                "inventory": f"/v1/inventory/workspace?query={offer_id}",
                "settlement": f"/v1/finance-control/workspace?query={offer_id}",
                "supplier": f"/v1/sourcing-intelligence/workspace?query={offer_id}",
            },
            "input_sha256": input_sha,
            "automatic_action_allowed": False,
            "external_write_allowed": False,
        }

    @classmethod
    def _batch_by_offer(cls, payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for candidate in payload.get("candidates") or []:
            market = candidate.get("market") or {}
            offer_id = str(market.get("external_item_id") or market.get("offer_id") or "").strip()
            if offer_id:
                result[offer_id] = candidate
        return result

    @classmethod
    def _accrual_by_sku(cls, payload: dict[str, Any], *, as_of: datetime) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        currency = payload.get("currency")
        if not cls._valid_currency(currency):
            return result
        for row in payload.get("rows") or []:
            sku = str(row.get("sku") or "").strip()
            evidence_ids = [str(item) for item in row.get("evidence_ids") or [] if str(item)]
            amount = row.get("actual_profit")
            if not sku or not evidence_ids or amount is None:
                continue
            money = cls._money(amount, currency, cls._timestamp(row.get("latest_effective_at"), fallback=as_of), evidence_ids[0])
            if money:
                result[sku] = {"status": "available", **money, "basis": "accrual_reconciled"}
        return result

    @classmethod
    def _cash_summary(cls, payload: dict[str, Any], display_currency: str) -> dict[str, Any]:
        available = [
            item["actual_cash_cm3"]
            for item in payload.get("cycles") or []
            if (item.get("actual_cash_cm3") or {}).get("status") == "available"
        ]
        if not available:
            return {
                "status": "no_data",
                "amount": None,
                "currency": display_currency,
                "reason": "reconciled_bank_cash_cm3_missing",
            }
        currencies = {item.get("currency") for item in available}
        if currencies != {display_currency}:
            return {
                "status": "blocked",
                "amount": None,
                "currency": display_currency,
                "reason": "cash_profit_currency_or_fx_mismatch",
            }
        return {
            "status": "available_unaggregated",
            "amount": None,
            "currency": display_currency,
            "cycle_count": len(available),
            "reason": "aggregate_money_evidence_snapshot_required",
        }

    @staticmethod
    def _highest_action(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not candidates:
            return None
        pilot = next((candidate for candidate in candidates if candidate["decision_class"] == "pilot"), None)
        selected = pilot or candidates[0]
        return {
            "candidate_id": selected["candidate_id"],
            "decision_class": selected["decision_class"],
            "next_action": selected["next_action"],
            "owner": selected["owner"],
        }

    @classmethod
    def _scope(
        cls,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, str]:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must include a timezone")
        if as_of > datetime.now(UTC):
            raise ValueError("as_of cannot be in the future")
        if not principal.can_access_store(store_ref):
            raise PermissionError("Authenticated identity is not authorized for store_ref")
        entity_ref = str(entity_scope.get("entity_ref") or "").strip()
        authority = str(entity_scope.get("authority_sha256") or "").strip()
        if entity_scope.get("status") != "ready" or not entity_ref or len(authority) != 64:
            raise ValueError("Profit Command requires one current entity scope grant")
        return {
            "tenant_ref": principal.tenant_ref,
            "entity_ref": entity_ref,
            "store_ref": store_ref,
            "scope_grant_authority_sha256": authority,
        }

    @staticmethod
    def _distribution(
        items: list[dict[str, Any]],
        selector: Callable[[dict[str, Any]], str],
    ) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for item in items:
            key = selector(item).strip() or "no_data"
            counts[key] = counts.get(key, 0) + 1
        return [
            {"key": key, "count": counts[key]}
            for key in sorted(counts)
        ]

    @classmethod
    def _aggregate_profit_metric(
        cls,
        candidates: list[dict[str, Any]],
        basis: str,
        field: str,
    ) -> dict[str, Any]:
        segments: dict[str, dict[str, Any]] = {}
        rejected = 0
        for candidate in candidates:
            profit = ((candidate.get("profit") or {}).get(basis) or {})
            value = profit.get(field)
            currency = profit.get("currency")
            evidence_ids = sorted(
                {
                    str(evidence_id)
                    for evidence_id in candidate.get("evidence_ids") or []
                    if str(evidence_id)
                }
            )
            if (
                profit.get("status") not in {"available", "available_unaggregated"}
                or value in (None, "")
                or not cls._valid_currency(currency)
                or not evidence_ids
            ):
                rejected += 1
                continue
            amount = cls._optional_decimal(value, field)
            if amount is None:
                rejected += 1
                continue
            segment = segments.setdefault(
                str(currency),
                {
                    "amount": Decimal("0"),
                    "candidate_count": 0,
                    "evidence_ids": set(),
                },
            )
            segment["amount"] += amount
            segment["candidate_count"] += 1
            segment["evidence_ids"].update(evidence_ids)

        if not segments:
            return {
                "status": "no_data",
                "basis": basis,
                "field": field,
                "amount": None,
                "currency": None,
                "included_candidate_count": 0,
                "excluded_candidate_count": rejected,
                "reason": "same_basis_currency_and_evidence_complete_values_missing",
            }

        projections = [
            {
                "currency": currency,
                "amount": cls._decimal_text(segment["amount"]),
                "candidate_count": segment["candidate_count"],
                "evidence_ids": sorted(segment["evidence_ids"]),
            }
            for currency, segment in sorted(segments.items())
        ]
        if len(projections) != 1:
            return {
                "status": "blocked",
                "basis": basis,
                "field": field,
                "amount": None,
                "currency": None,
                "included_candidate_count": sum(
                    item["candidate_count"] for item in projections
                ),
                "excluded_candidate_count": rejected,
                "currency_segments": projections,
                "reason": "cross_currency_aggregation_requires_evidenced_fx_basis",
            }

        projection = projections[0]
        return {
            "status": "available",
            "basis": basis,
            "field": field,
            "amount": projection["amount"],
            "currency": projection["currency"],
            "included_candidate_count": projection["candidate_count"],
            "excluded_candidate_count": rejected,
            "evidence_ids": projection["evidence_ids"],
            "reason": None,
        }

    @staticmethod
    def _blocker(code: str) -> dict[str, Any]:
        return {
            "code": code,
            "severity": "P0" if "currency" in code or "fx" in code else "P1",
            "owner": "finance-control" if "profit" in code or "currency" in code or "fx" in code else "data-governance",
            "sla": "before repricing, purchase, advertising, listing, or Pilot expansion",
            "next": "Resolve the exact source Evidence and rerun the immutable decision snapshot.",
        }

    @classmethod
    def _proposal_projection(cls, row: ProfitPilotProposalRow, *, idempotent: bool) -> dict[str, Any]:
        return {
            "proposal_id": row.id,
            "snapshot_id": row.snapshot_id,
            "status": row.status,
            "scope": {
                "tenant_ref": row.tenant_ref,
                "entity_ref": row.entity_ref,
                "store_ref": row.store_ref,
            },
            "candidate_id": row.candidate_id,
            "request_evidence_id": row.request_evidence_id,
            "proposal": row.proposal_json,
            "idempotent": idempotent,
            "approval_created": False,
            "permit_created": False,
            "pilot_started": False,
            "external_write_allowed": False,
        }

    @staticmethod
    def _nested(value: dict[str, Any], *keys: str) -> Any:
        current: Any = value
        for key in keys:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current

    @classmethod
    def _money(
        cls,
        amount: Any,
        currency: Any,
        occurred_at: datetime,
        evidence_id: str,
    ) -> dict[str, Any] | None:
        parsed = cls._optional_decimal(amount, "amount")
        if parsed is None or not cls._valid_currency(currency):
            return None
        return MoneyAmount(parsed, str(currency), occurred_at, evidence_id).to_dict()

    @staticmethod
    def _timestamp(value: Any, *, fallback: datetime) -> datetime:
        if value:
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                return fallback.astimezone(UTC)
            if parsed.tzinfo is not None and parsed.utcoffset() is not None:
                return parsed.astimezone(UTC)
        return fallback.astimezone(UTC)

    @staticmethod
    def _currency(value: Any) -> str:
        if not ProfitCommandWorkspace._valid_currency(value):
            raise ValueError("display_currency must be a three-letter uppercase ASCII currency")
        return str(value)

    @staticmethod
    def _valid_currency(value: Any) -> bool:
        return isinstance(value, str) and len(value) == 3 and value.isascii() and value.isalpha() and value.isupper()

    @staticmethod
    def _optional_decimal(value: Any, field: str) -> Decimal | None:
        if value in (None, ""):
            return None
        if isinstance(value, (bool, float)):
            raise ValueError(f"{field} must not use binary floating point")
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be a finite decimal") from exc
        if not parsed.is_finite():
            raise ValueError(f"{field} must be a finite decimal")
        return parsed

    @classmethod
    def _optional_positive_decimal(cls, value: Any, field: str) -> Decimal | None:
        parsed = cls._optional_decimal(value, field)
        if parsed is not None and parsed <= 0:
            raise ValueError(f"{field} must be positive")
        return parsed

    @staticmethod
    def _decimal_text(value: Decimal | None) -> str | None:
        return format(value, "f") if value is not None else None

    @staticmethod
    def _required(value: Any, field: str, max_length: int) -> str:
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > max_length:
            raise ValueError(f"{field} is required and must be at most {max_length} characters")
        return value.strip()

    @staticmethod
    def _canonical(value: Any) -> bytes:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()

    @classmethod
    def _hash(cls, value: Any) -> str:
        return hashlib.sha256(cls._canonical(value)).hexdigest()

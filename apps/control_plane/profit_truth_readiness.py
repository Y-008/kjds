from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .facts import FactRecordRow
from .finance import FinanceEntryRow, FxRateRow
from .market_recon_bundle import (
    MarketReconBundleItemRow,
    MarketReconBundleRunRow,
)
from .ozon_finance_allocation import OzonFinanceAllocationWorkspace
from .profit_command import ProfitDecisionSnapshotRow
from .profit_cost_evidence import ProfitCostEvidenceWorkspace
from .security import Principal
from .variant_identity_resolution import VariantIdentityResolutionWorkspace


class ProfitTruthReadinessWorkspace:
    """Compose retained evidence into a read-only profit truth gate."""

    CONTRACT_ID = "kjds-profit-truth-readiness-v1"

    def __init__(
        self,
        *,
        engine,
        finance_allocation: OzonFinanceAllocationWorkspace | None = None,
        cost_evidence: ProfitCostEvidenceWorkspace | None = None,
        variant_identity: VariantIdentityResolutionWorkspace | None = None,
    ) -> None:
        self.engine = engine
        self.finance_allocation = (
            finance_allocation or OzonFinanceAllocationWorkspace()
        )
        self.cost_evidence = cost_evidence or ProfitCostEvidenceWorkspace()
        self.variant_identity = (
            variant_identity or VariantIdentityResolutionWorkspace()
        )

    def project(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        display_currency: str = "CNY",
    ) -> dict[str, Any]:
        scope, authority_scope = self._scope(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        display_currency = self._currency(display_currency)
        data = self._load(
            scope=scope,
            authority_sha256=authority_scope[
                "scope_grant_authority_sha256"
            ],
            as_of=as_of,
        )
        bundle = data["bundle"]
        items = data["items"]
        by_kind: dict[str, list[MarketReconBundleItemRow]] = {}
        for row in items:
            by_kind.setdefault(row.artifact_kind, []).append(row)

        identity_sources = self._identity_sources(
            scope=scope,
            by_kind=by_kind,
        )
        variant_projection = self.variant_identity.project(
            scope=scope,
            sources=identity_sources,
        )
        operations = self._finance_operations(
            by_kind.get("ozon_finance", [])
        )
        listing_mappings = self._listing_mappings(
            by_kind.get("ozon_product_info", [])
        )
        finance_projection = self.finance_allocation.project(
            scope=authority_scope,
            operations={
                "scope": authority_scope,
                "operations": [item["operation"] for item in operations],
                "evidence_refs": sorted(
                    {
                        evidence_id
                        for item in operations
                        for evidence_id in item["evidence_refs"]
                    }
                ),
            },
            listing_mappings={
                "scope": authority_scope,
                "mappings": listing_mappings,
            },
            currency_evidence=None,
        )
        required_fx_pairs = self._required_fx_pairs(
            product_rows=by_kind.get("ozon_product_info", []),
            display_currency=display_currency,
        )
        complete_fx = [
            self._fx_projection(row, scope=scope)
            for row in data["scoped_fx"]
            if row.expires_at is not None
            and self._aware(row.effective_at) <= as_of
            and as_of < self._aware(row.expires_at)
            and row.source_type
            and row.authority
            and row.purposes_json
            and "scenario_profit" in row.purposes_json
            and row.intake_content_sha256
            and row.idempotency_key
            and (row.base_currency, row.quote_currency)
            in required_fx_pairs
        ]
        covered_fx_pairs = {
            (record["source_currency"], record["quote_currency"])
            for record in complete_fx
        }
        missing_fx_pairs = sorted(required_fx_pairs - covered_fx_pairs)
        cost_projection = self.cost_evidence.project(
            scope=scope,
            sku_inputs=self._cost_inputs(
                scope=scope,
                product_rows=by_kind.get("ozon_product_info", []),
                variant_projection=variant_projection,
                fx_bases=complete_fx,
                display_currency=display_currency,
            ),
            as_of=as_of,
        )
        fact_counts = Counter(row.fact_type for row in data["facts"])
        entry_counts = Counter(row.entry_kind for row in data["finance_entries"])
        profit_books = self._profit_books(
            fact_counts=fact_counts,
            entry_counts=entry_counts,
            decision_snapshot_count=len(data["decision_snapshots"]),
            display_currency=display_currency,
        )
        stage_counts = (
            dict(bundle.stage_counts_json)
            if bundle is not None
            else {
                "raw_evidence": 0,
                "normalized_observation": 0,
                "reviewed_observation": 0,
                "formal_fact": 0,
                "decision_snapshot": 0,
            }
        )
        stage_counts["formal_fact_database"] = len(data["facts"])
        stage_counts["decision_snapshot_database"] = len(
            data["decision_snapshots"]
        )
        blockers = self._blockers(
            bundle=bundle,
            finance_projection=finance_projection,
            variant_projection=variant_projection,
            cost_projection=cost_projection,
            missing_fx_pair_count=len(missing_fx_pairs),
            legacy_fx_count=data["legacy_fx_count"],
            profit_books=profit_books,
        )
        source_total = bundle.source_total if bundle else 0
        retained = (
            bundle.accepted_count + bundle.quarantined_count
            if bundle
            else 0
        )
        payload = {
            "contract_id": self.CONTRACT_ID,
            "status": "blocked" if blockers else "ready_for_profit_validation",
            "scope": scope,
            "scope_grant_authority_sha256": authority_scope[
                "scope_grant_authority_sha256"
            ],
            "as_of": as_of.astimezone(UTC).isoformat(),
            "display_currency": display_currency,
            "data_chain": {
                "path": [
                    "raw_evidence",
                    "normalized_observation",
                    "reviewed_observation",
                    "formal_fact",
                    "decision_snapshot",
                    "scenario_profit",
                    "accrual_profit",
                    "settlement_profit",
                    "cash_profit",
                ],
                "stage_counts": stage_counts,
                "source_total": source_total,
                "retained_total": retained,
                "conservation_passed": retained == source_total,
                "raw_data_deleted": False,
            },
            "summary": {
                "sku_count": len(
                    by_kind.get("ozon_product_info", [])
                ),
                "identity_source_count": variant_projection["summary"][
                    "source_total"
                ],
                "finance_operation_count": finance_projection["summary"][
                    "source_total"
                ],
                "finance_entry_proposal_count": finance_projection[
                    "summary"
                ]["finance_entry_proposals"],
                "complete_scoped_fx_count": len(complete_fx),
                "legacy_unscoped_fx_count": data["legacy_fx_count"],
                "cost_evidence_request_count": cost_projection["summary"][
                    "evidence_request_count"
                ],
                "formal_fact_count": len(data["facts"]),
                "finance_entry_count": len(data["finance_entries"]),
                "decision_snapshot_count": len(data["decision_snapshots"]),
                "blocker_count": len(blockers),
            },
            "fx_readiness": {
                "status": (
                    "not_required"
                    if not required_fx_pairs
                    else "blocked"
                    if missing_fx_pairs
                    else "ready"
                ),
                "complete_scoped_records": complete_fx,
                "legacy_unscoped_record_count": data["legacy_fx_count"],
                "legacy_records_decision_eligible": False,
                "required_pair": ", ".join(
                    f"{source}/{quote}"
                    for source, quote in sorted(required_fx_pairs)
                ),
                "required_pairs": [
                    {
                        "source_currency": source,
                        "quote_currency": quote,
                        "status": (
                            "ready"
                            if (source, quote) in covered_fx_pairs
                            else "blocked"
                        ),
                    }
                    for source, quote in sorted(required_fx_pairs)
                ],
                "record_endpoint": "/v1/profit-command/fx-evidence",
            },
            "variant_identity": variant_projection,
            "finance_allocation": finance_projection,
            "cost_evidence": cost_projection,
            "profit_books": profit_books,
            "blockers": blockers,
            "drillthrough": {
                "bundle_quality": (
                    f"/v1/intelligence-ingestion/bundles/{bundle.id}/quality"
                    if bundle
                    else None
                ),
                "profit_workspace": "/v1/profit-command/workspace",
                "profit_remediation": "/v1/profit-command/remediation",
                "finance_control": "/v1/finance-control/workspace",
                "oms": "/v1/oms/workspace",
                "profit_ledger": "/v1/profit-ledger",
            },
            "control_envelope": {
                "read_only_projection": True,
                "missing_values_guessed": False,
                "currency_inferred": False,
                "proportional_finance_allocation_performed": False,
                "formal_fact_promoted": False,
                "finance_entry_persisted": False,
                "pilot_proposal_allowed": False,
                "automatic_action_allowed": False,
                "external_write_allowed": False,
            },
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def _load(
        self,
        *,
        scope: dict[str, str],
        authority_sha256: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        with Session(self.engine) as session:
            bundle = session.scalar(
                select(MarketReconBundleRunRow)
                .where(
                    MarketReconBundleRunRow.tenant_ref
                    == scope["tenant_ref"],
                    MarketReconBundleRunRow.entity_ref
                    == scope["entity_ref"],
                    MarketReconBundleRunRow.store_ref
                    == scope["store_ref"],
                    MarketReconBundleRunRow.as_of <= as_of,
                )
                .order_by(
                    MarketReconBundleRunRow.as_of.desc(),
                    MarketReconBundleRunRow.id.desc(),
                )
                .limit(1)
            )
            items = []
            if bundle is not None:
                items = list(
                    session.scalars(
                        select(MarketReconBundleItemRow)
                        .where(
                            MarketReconBundleItemRow.bundle_id == bundle.id,
                            MarketReconBundleItemRow.tenant_ref
                            == scope["tenant_ref"],
                            MarketReconBundleItemRow.entity_ref
                            == scope["entity_ref"],
                            MarketReconBundleItemRow.store_ref
                            == scope["store_ref"],
                        )
                        .order_by(
                            MarketReconBundleItemRow.artifact_kind,
                            MarketReconBundleItemRow.record_index,
                            MarketReconBundleItemRow.id,
                        )
                    )
                )
            scoped_fx = list(
                session.scalars(
                    select(FxRateRow).where(
                        FxRateRow.tenant_ref == scope["tenant_ref"],
                        FxRateRow.entity_ref == scope["entity_ref"],
                        FxRateRow.store_ref == scope["store_ref"],
                        FxRateRow.scope_grant_authority_sha256
                        == authority_sha256,
                        FxRateRow.recorded_at <= as_of,
                    )
                )
            )
            legacy_fx_count = len(
                list(
                    session.scalars(
                        select(FxRateRow.id).where(
                            FxRateRow.tenant_ref.is_(None)
                        )
                    )
                )
            )
            facts = list(
                session.scalars(
                    select(FactRecordRow).where(
                        FactRecordRow.tenant_ref == scope["tenant_ref"],
                        FactRecordRow.entity_ref == scope["entity_ref"],
                        FactRecordRow.store_ref == scope["store_ref"],
                        FactRecordRow.scope_grant_authority_sha256
                        == authority_sha256,
                        FactRecordRow.recorded_at <= as_of,
                    )
                )
            )
            finance_entries = list(
                session.scalars(
                    select(FinanceEntryRow).where(
                        FinanceEntryRow.tenant_ref == scope["tenant_ref"],
                        FinanceEntryRow.entity_ref == scope["entity_ref"],
                        FinanceEntryRow.store_ref == scope["store_ref"],
                        FinanceEntryRow.scope_grant_authority_sha256
                        == authority_sha256,
                        FinanceEntryRow.recorded_at <= as_of,
                    )
                )
            )
            decision_snapshots = list(
                session.scalars(
                    select(ProfitDecisionSnapshotRow).where(
                        ProfitDecisionSnapshotRow.tenant_ref
                        == scope["tenant_ref"],
                        ProfitDecisionSnapshotRow.entity_ref
                        == scope["entity_ref"],
                        ProfitDecisionSnapshotRow.store_ref
                        == scope["store_ref"],
                        ProfitDecisionSnapshotRow.as_of <= as_of,
                    )
                )
            )
            if bundle is not None:
                session.expunge(bundle)
            for row in [
                *items,
                *scoped_fx,
                *facts,
                *finance_entries,
                *decision_snapshots,
            ]:
                session.expunge(row)
        return {
            "bundle": bundle,
            "items": items,
            "scoped_fx": scoped_fx,
            "legacy_fx_count": legacy_fx_count,
            "facts": facts,
            "finance_entries": finance_entries,
            "decision_snapshots": decision_snapshots,
        }

    @staticmethod
    def _identity_sources(
        *,
        scope: dict[str, str],
        by_kind: dict[str, list[MarketReconBundleItemRow]],
    ) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []
        for kind in ("ozon_catalog", "ozon_product_info"):
            for row in by_kind.get(kind, []):
                sources.append(
                    {
                        "source_ref": f"bundle-item:{row.id}",
                        "source_kind": kind,
                        "scope": scope,
                        "artifact_evidence_id": row.artifact_evidence_id,
                        "payload": row.payload_json,
                    }
                )
        for row in by_kind.get("ozon_finance", []):
            for operation in row.payload_json.get("operations") or []:
                operation_id = str(operation.get("operation_id") or "")
                for index, item in enumerate(operation.get("items") or []):
                    sources.append(
                        {
                            "source_ref": (
                                f"finance-item:{operation_id}:{index}:"
                                f"{row.id}"
                            ),
                            "source_kind": "ozon_finance_item",
                            "scope": scope,
                            "artifact_evidence_id": row.artifact_evidence_id,
                            "payload": {
                                "platform_namespace": "ozon",
                                "items": [item],
                            },
                        }
                    )
        return sources

    @staticmethod
    def _finance_operations(
        rows: list[MarketReconBundleItemRow],
    ) -> list[dict[str, Any]]:
        values = []
        for row in rows:
            for operation in row.payload_json.get("operations") or []:
                values.append(
                    {
                        "operation": operation,
                        "evidence_refs": [row.artifact_evidence_id],
                    }
                )
        return values

    @staticmethod
    def _listing_mappings(
        rows: list[MarketReconBundleItemRow],
    ) -> list[dict[str, Any]]:
        mappings = []
        for row in rows:
            payload = row.payload_json
            mappings.append(
                {
                    "mapping_id": f"bundle-map:{row.id}",
                    "platform_sku": str(payload.get("sku") or ""),
                    "canonical_sku": str(
                        payload.get("offer_id") or row.record_key
                    ),
                    "evidence_id": row.artifact_evidence_id,
                }
            )
        return mappings

    @classmethod
    def _cost_inputs(
        cls,
        *,
        scope: dict[str, str],
        product_rows: list[MarketReconBundleItemRow],
        variant_projection: dict[str, Any],
        fx_bases: list[dict[str, Any]],
        display_currency: str,
    ) -> list[dict[str, Any]]:
        resolution_by_source = {
            source_ref: resolution
            for resolution in variant_projection["exact_resolutions"]
            for source_ref in resolution["source_refs"]
        }
        inputs = []
        for row in product_rows:
            payload = row.payload_json
            source_ref = f"bundle-item:{row.id}"
            resolution = resolution_by_source.get(source_ref)
            currencies = {
                str(payload.get("currency_code") or "").strip().upper()
            }
            market = (
                (payload.get("price_indexes") or {}).get(
                    "ozon_index_data"
                )
                or {}
            )
            currencies.add(
                str(
                    market.get("minimal_price_currency") or ""
                ).strip().upper()
            )
            currencies.discard("")
            inputs.append(
                {
                    "scope": scope,
                    "sku": str(payload.get("offer_id") or row.record_key),
                    "quote_currency": display_currency,
                    "source_currencies": sorted(currencies),
                    "variant_identity": {
                        "scope": scope,
                        "status": "exact" if resolution else "candidate",
                        "variant_ref": (
                            resolution["resolution_id"] if resolution else ""
                        ),
                        "evidence_id": (
                            resolution["evidence_refs"][0]
                            if resolution
                            and resolution["evidence_refs"]
                            else ""
                        ),
                    },
                    "quantity": {
                        "scope": scope,
                        "value": None,
                        "basis": "unresolved",
                        "evidence_id": "",
                    },
                    "cost_evidence": [],
                    "fx_bases": fx_bases,
                    "book_evidence": [],
                }
            )
        return inputs

    @staticmethod
    def _fx_projection(
        row: FxRateRow,
        *,
        scope: dict[str, str],
    ) -> dict[str, Any]:
        return {
            "scope": scope,
            "fx_basis_id": row.id,
            "evidence_id": row.evidence_id,
            "evidence_level": "reviewed",
            "source_currency": row.base_currency,
            "quote_currency": row.quote_currency,
            "rate": str(row.rate),
            "effective_at": row.effective_at.isoformat(),
            "effective_until": (
                row.expires_at.isoformat() if row.expires_at else None
            ),
            "source_type": row.source_type,
            "authority": row.authority,
            "purposes": list(row.purposes_json or []),
            "content_sha256": row.intake_content_sha256,
        }

    @classmethod
    def _required_fx_pairs(
        cls,
        *,
        product_rows: list[MarketReconBundleItemRow],
        display_currency: str,
    ) -> set[tuple[str, str]]:
        source_currencies: set[str] = set()
        for row in product_rows:
            payload = row.payload_json
            own_currency = cls._currency_or_none(payload.get("currency_code"))
            if own_currency:
                source_currencies.add(own_currency)
            market = (payload.get("price_indexes") or {}).get("ozon_index_data") or {}
            market_currency = cls._currency_or_none(
                market.get("minimal_price_currency")
            )
            if market_currency:
                source_currencies.add(market_currency)
        return {
            (source_currency, display_currency)
            for source_currency in source_currencies
            if source_currency != display_currency
        }

    @staticmethod
    def _profit_books(
        *,
        fact_counts: Counter,
        entry_counts: Counter,
        decision_snapshot_count: int,
        display_currency: str,
    ) -> dict[str, Any]:
        accrual_count = sum(
            fact_counts[fact_type]
            for fact_type in (
                "ozon_order",
                "ozon_accrual",
                "ozon_fee",
                "ozon_return",
            )
        )
        settlement_count = (
            fact_counts["ozon_settlement"]
            + entry_counts["platform_settlement"]
        )
        cash_count = entry_counts["bank_receipt"]
        return {
            "scenario_profit": {
                "status": (
                    "available_unaggregated"
                    if decision_snapshot_count
                    else "no_data"
                ),
                "record_count": decision_snapshot_count,
                "amount": None,
                "currency": display_currency,
            },
            "accrual_profit": {
                "status": "available_unaggregated" if accrual_count else "no_data",
                "record_count": accrual_count,
                "amount": None,
                "currency": display_currency,
            },
            "settlement_profit": {
                "status": "available_unaggregated" if settlement_count else "no_data",
                "record_count": settlement_count,
                "amount": None,
                "currency": display_currency,
            },
            "cash_profit": {
                "status": "available_unaggregated" if cash_count else "no_data",
                "record_count": cash_count,
                "amount": None,
                "currency": display_currency,
            },
            "strictly_separated": True,
            "cross_book_promotion_performed": False,
            "client_side_profit_calculation_allowed": False,
        }

    @staticmethod
    def _blockers(
        *,
        bundle: MarketReconBundleRunRow | None,
        finance_projection: dict[str, Any],
        variant_projection: dict[str, Any],
        cost_projection: dict[str, Any],
        missing_fx_pair_count: int,
        legacy_fx_count: int,
        profit_books: dict[str, Any],
    ) -> list[dict[str, Any]]:
        values: list[tuple[str, int, str]] = []
        if bundle is None:
            values.append(("market_recon_bundle_missing", 1, "data-operations"))
        if missing_fx_pair_count:
            values.append(
                (
                    "complete_scoped_fx_missing",
                    missing_fx_pair_count,
                    "treasury-control",
                )
            )
        if legacy_fx_count:
            values.append(
                (
                    "legacy_unscoped_fx_not_decision_eligible",
                    legacy_fx_count,
                    "treasury-control",
                )
            )
        finance_missing = finance_projection["summary"]["source_total"] - finance_projection[
            "summary"
        ]["finance_entry_proposals"]
        if finance_missing:
            values.append(
                (
                    "ozon_finance_operations_not_entry_eligible",
                    finance_missing,
                    "marketplace-finance",
                )
            )
        unresolved = variant_projection["summary"]["unresolved"]
        quarantined = variant_projection["summary"]["quarantined"]
        if unresolved or quarantined:
            values.append(
                (
                    "variant_identity_review_required",
                    unresolved + quarantined,
                    "catalog-operations",
                )
            )
        requests = cost_projection["summary"]["evidence_request_count"]
        if requests:
            values.append(
                (
                    "fifteen_cost_evidence_incomplete",
                    requests,
                    "profit-operations",
                )
            )
        for book in (
            "accrual_profit",
            "settlement_profit",
            "cash_profit",
        ):
            if profit_books[book]["status"] == "no_data":
                values.append((f"{book}_missing", 1, "finance-control"))
        return [
            {
                "code": code,
                "affected_count": count,
                "owner": owner,
                "missing_value_guessed": False,
                "automatic_resolution_allowed": False,
            }
            for code, count, owner in sorted(values)
        ]

    @staticmethod
    def _scope(
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> tuple[dict[str, str], dict[str, str]]:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must include a timezone")
        if not principal.can_access_store(store_ref):
            raise PermissionError("Store is outside the authenticated scope")
        if entity_scope.get("status") != "ready":
            raise PermissionError("Current exact entity scope authority is required")
        entity_ref = str(entity_scope.get("entity_ref") or "").strip()
        authority = str(entity_scope.get("authority_sha256") or "").strip().lower()
        if not entity_ref or len(authority) != 64:
            raise PermissionError("Current exact entity scope authority is incomplete")
        scope = {
            "tenant_ref": principal.tenant_ref,
            "entity_ref": entity_ref,
            "store_ref": store_ref,
        }
        return scope, {
            **scope,
            "scope_grant_authority_sha256": authority,
        }

    @staticmethod
    def _currency(value: str) -> str:
        normalized = str(value or "").strip()
        if (
            len(normalized) != 3
            or not normalized.isascii()
            or not normalized.isalpha()
            or normalized != normalized.upper()
        ):
            raise ValueError(
                "display_currency must be a three-letter uppercase ASCII currency"
            )
        return normalized

    @staticmethod
    def _currency_or_none(value: Any) -> str | None:
        normalized = str(value or "").strip().upper()
        if (
            len(normalized) == 3
            and normalized.isascii()
            and normalized.isalpha()
        ):
            return normalized
        return None

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                default=str,
            ).encode()
        ).hexdigest()

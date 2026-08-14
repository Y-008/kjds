from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.control_plane.automated_commerce import AutomatedCommerceLoop
from apps.control_plane.security import Principal
from apps.control_plane.sourcing import SourcePlatform

NOW = datetime(2026, 8, 8, 10, 0, tzinfo=UTC)
SCOPE = {
    "status": "ready",
    "entity_ref": "entity-1",
    "authority_sha256": "a" * 64,
}
PROJECTED_SCOPE = {
    "tenant_ref": "tenant-1",
    "entity_ref": "entity-1",
    "store_ref": "ozon-primary",
    "scope_grant_authority_sha256": "a" * 64,
}
SOURCING_AUTHORITY = {
    "pim_snapshot_sha256": "1" * 64,
    "market_radar_snapshot_sha256": "2" * 64,
    "batch_opportunity_snapshot_sha256": "3" * 64,
    "artifact_evidence_authority_sha256": "4" * 64,
}
PRINCIPAL = Principal(
    actor_id="operator-1",
    roles=frozenset({"operator"}),
    tenant_ref="tenant-1",
)


def _hash(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _seal(value: dict) -> dict:
    result = dict(value)
    result["snapshot_sha256"] = _hash(result)
    return result


def _reseal(value: dict) -> dict:
    result = dict(value)
    result.pop("snapshot_sha256", None)
    return _seal(result)


class Scenario:
    def __init__(self, *, complete: bool, cm3: str = "18.50") -> None:
        self.cost_complete = complete
        self.cm3_cny = Decimal(cm3)
        self.cm3_rate = Decimal("0.185")
        self.break_even_price_rub = Decimal("721.00")
        self.missing_cost_evidence = [] if complete else ["return"]
        self.unknown_costs = [] if complete else ["return"]
        self.evidence = ["ev-profit"]

    def explain(self):
        return {"release_ready": self.cost_complete, "cm3_cny": str(self.cm3_cny)}


class Store:
    def __init__(self, *, complete: bool = True, cm3: str = "18.50") -> None:
        self.draft = SimpleNamespace(
            id="lst-1",
            product_id="prd-1",
            offer_id="off-supplier-1",
            scenario_id="scn-1",
            created_at="2026-08-08T08:00:00+00:00",
        )
        self.offer = SimpleNamespace(
            id="off-supplier-1",
            product_id="prd-1",
            platform=SourcePlatform.ALIBABA_1688,
            supplier_ref="supplier-1",
            external_id="1688-item-1",
            source_url="https://detail.1688.com/offer/1688-item-1.html",
            attributes={"supplier_store_url": "https://supplier.1688.com/"},
            evidence_ref="ev-rfq",
        )
        self.scenario = Scenario(complete=complete, cm3=cm3)
        self.scenario.offer_id = self.offer.id

    def list_listing_drafts_scoped(self, **_kwargs):
        return [self.draft]

    def get_offer(self, offer_id):
        if offer_id != self.offer.id:
            raise KeyError(offer_id)
        return self.offer

    def get_scenario(self, scenario_id):
        if scenario_id != "scn-1":
            raise KeyError(scenario_id)
        return self.scenario


class Catalog:
    def __init__(
        self,
        *,
        bound: bool = True,
        scope: dict | None = None,
        as_of: str | None = None,
        snapshot_valid: bool = True,
        items: list[dict] | None = None,
        status: str = "ready",
        source_gaps: list[str] | None = None,
    ) -> None:
        self.bound = bound
        self.scope = scope or PROJECTED_SCOPE
        self.as_of = as_of or NOW.isoformat()
        self.snapshot_valid = snapshot_valid
        self.items = items
        self.status = status
        self.source_gaps = source_gaps or []

    def latest(self, **_kwargs):
        items = self.items
        if items is None:
            items = [
                {
                    "offer_id": "RU-001",
                    "marketplace_sku": "2216781923",
                    "canonical_product_id": "prd-1" if self.bound else None,
                    "observed_at": "2026-08-08T09:00:00+00:00",
                    "source_evidence_id": "ev-ozon-readback",
                }
            ]
        result = _seal({
            "contract_id": "kjds-scoped-marketplace-catalog-v1",
            "status": self.status,
            "as_of": self.as_of,
            "scope": self.scope,
            "items": items,
            "counts": {
                "queried_in_exact_store_scope": len(items),
                "included": len(items),
                "excluded": 0,
                "bound_to_canonical_product": sum(
                    bool(item.get("canonical_product_id")) for item in items
                ),
            },
            "excluded": {
                "count": 0,
                "by_reason": {},
                "details_disclosed": False,
            },
            "source_gaps": self.source_gaps,
            "blockers": [],
            "control_envelope": {
                "read_only": True,
                "external_write_allowed": False,
            },
        })
        if not self.snapshot_valid:
            result["snapshot_sha256"] = "f" * 64
        return result


class AiListing:
    def __init__(self) -> None:
        self.create_args = None
        self.process_args = None

    def list(self, **_kwargs):
        return {
            "items": [
                {
                    "id": "air-1",
                    "status": "listing_draft_created",
                    "current_stage": "listing_draft_created",
                    "bindings": {"product_id": "prd-1"},
                    "internal_refs": {"listing_draft_id": "lst-1"},
                    "next_action": {"code": "independent_listing_review_required"},
                }
            ]
        }

    def create(self, **kwargs):
        self.create_args = kwargs
        return {"id": "air-new"}

    def process(self, run_id, **kwargs):
        self.process_args = {"run_id": run_id, **kwargs}
        return {
            "id": run_id,
            "status": "evidence_review_required",
            "next_action": {"code": "formal_offer_required"},
        }


class SourcingIntelligence:
    def __init__(
        self,
        *,
        fail: bool = False,
        scope: dict | None = None,
        as_of: str | None = None,
        total_work_items: int = 1,
        snapshot_valid: bool = True,
        status: str = "partial",
        item_status: str = "partial",
        source_gaps: list[str] | None = None,
    ) -> None:
        self.fail = fail
        self.calls = 0
        self.scope = scope or PROJECTED_SCOPE
        self.as_of = as_of or NOW.isoformat()
        self.total_work_items = total_work_items
        self.snapshot_valid = snapshot_valid
        self.status = status
        self.item_status = item_status
        self.source_gaps = source_gaps or []

    def project(self, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError("scoped sourcing unavailable")
        item = {
            "work_item_key": "product:prd-1",
            "canonical_product_ids": ["prd-1"],
            "readiness": {
                "status": self.item_status,
                "rfq_draft_ready": True,
                "three_accepted_quotes_ready": False,
            },
            "rfq_and_quotes": {
                "rfq_packages": [{"package_id": "rfq-1"}],
                "dispatch_proofs": [],
                "quotes": [],
                "accepted_unique_suppliers": [],
                "rfq_draft_ready": True,
                "three_accepted_quotes_ready": False,
            },
            "next": "Collect and independently accept three exact-product quotes.",
        }
        result = _seal({
            "contract_id": (
                "kjds-native-exact-scope-sourcing-intelligence-workspace-v1"
            ),
            "status": self.status,
            "as_of": self.as_of,
            "scope": self.scope,
            "query": {
                "page_size": 200,
                "cursor": kwargs.get("cursor"),
                "next_cursor": None,
                "target_purchase_quantity": 1,
            },
            "counts": {
                "total_work_items": self.total_work_items,
                "page_work_items": 1,
            },
            "upstream_authority": SOURCING_AUTHORITY,
            "source_gaps": self.source_gaps,
            "control_envelope": {
                "read_only": True,
                "supplier_contacted": False,
                "rfq_dispatched": False,
                "quote_accepted": False,
                "purchase_order_created": False,
                "payment_created": False,
                "approval_created": False,
                "permit_created": False,
                "external_write_allowed": False,
            },
            "work_items": [item],
        })
        if not self.snapshot_valid:
            result["snapshot_sha256"] = "f" * 64
        return result


class PaginatedSourcingIntelligence:
    def __init__(self) -> None:
        self.cursors = []

    def project(self, **kwargs):
        cursor = kwargs.get("cursor")
        self.cursors.append(cursor)
        common = {
            "contract_id": (
                "kjds-native-exact-scope-sourcing-intelligence-workspace-v1"
            ),
            "status": "partial",
            "as_of": NOW.isoformat(),
            "scope": PROJECTED_SCOPE,
            "source_gaps": [],
            "upstream_authority": SOURCING_AUTHORITY,
            "counts": {"total_work_items": 2, "page_work_items": 1},
            "control_envelope": {
                "read_only": True,
                "supplier_contacted": False,
                "rfq_dispatched": False,
                "quote_accepted": False,
                "purchase_order_created": False,
                "payment_created": False,
                "approval_created": False,
                "permit_created": False,
                "external_write_allowed": False,
            },
        }
        if cursor is None:
            return _seal({
                **common,
                "query": {
                    "page_size": 200,
                    "cursor": None,
                    "next_cursor": "page-2",
                    "target_purchase_quantity": 1,
                },
                "work_items": [
                    {
                        "work_item_key": "product:prd-0",
                        "canonical_product_ids": ["prd-0"],
                        "readiness": {"status": "partial"},
                        "rfq_and_quotes": {},
                        "next": "Continue supplier research.",
                    }
                ],
            })
        return _seal({
            **common,
            "query": {
                "page_size": 200,
                "cursor": "page-2",
                "next_cursor": None,
                "target_purchase_quantity": 1,
            },
            "work_items": [
                {
                    "work_item_key": "product:prd-1",
                    "canonical_product_ids": ["prd-1"],
                    "readiness": {"status": "partial"},
                    "rfq_and_quotes": {
                        "rfq_draft_ready": True,
                        "three_accepted_quotes_ready": False,
                    },
                    "next": "Collect three exact-product quotes.",
                }
            ],
        })


class StatusDriftPaginatedSourcing(PaginatedSourcingIntelligence):
    def project(self, **kwargs):
        result = super().project(**kwargs)
        if kwargs.get("cursor") == "page-2":
            result["status"] = "ready"
            result = _reseal(result)
        return result


def service(
    *,
    complete: bool = True,
    cm3: str = "18.50",
    bound: bool = True,
    sourcing_intelligence=None,
):
    ai = AiListing()
    return AutomatedCommerceLoop(
        ai_listing=ai,
        repository=SimpleNamespace(
            get_product=lambda product_id: SimpleNamespace(
                id=product_id,
                sku="RU-001",
                name="Storage bag",
            )
        ),
        sourcing_store=Store(complete=complete, cm3=cm3),
        scoped_catalog=Catalog(bound=bound),
        sourcing_intelligence=sourcing_intelligence,
    ), ai


def test_ozon_listing_url_resolves_exact_supplier_purchase_link_and_profit() -> None:
    loop, _ = service()

    result = loop.workspace(
        principal=PRINCIPAL,
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=NOW,
        listing_ref="https://www.ozon.ru/product/storage-bag-2216781923/",
    )

    assert result["lookup"]["normalized_value"] == "2216781923"
    assert result["counts"] == {
        "items": 1,
        "profit_recommended": 1,
        "awaiting_profit_evidence": 0,
        "purchase_links_ready": 1,
        "platform_links_observed": 1,
        "rfq_drafts_ready": 0,
        "three_accepted_quotes_ready": 0,
        "rfq_blocked": 0,
    }
    item = result["items"][0]
    assert item["identity"]["supplier_offer_id"] == "off-supplier-1"
    assert item["listing"]["listing_url"] == "https://www.ozon.ru/product/2216781923/"
    assert item["sourcing"]["purchase_url"].startswith("https://detail.1688.com/")
    assert item["sourcing"]["supplier_store_url"] == "https://supplier.1688.com/"
    assert item["sourcing"]["automatic_order"] is False
    assert item["profit_recommendation"]["verdict"] == "recommended"


def test_workspace_projects_existing_scoped_rfq_readiness_once() -> None:
    sourcing_intelligence = SourcingIntelligence()
    loop, _ = service(sourcing_intelligence=sourcing_intelligence)

    result = loop.workspace(
        principal=PRINCIPAL,
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=NOW,
    )

    assert sourcing_intelligence.calls == 1
    assert result["status"] == "partial"
    assert result["counts"]["rfq_drafts_ready"] == 1
    assert result["counts"]["three_accepted_quotes_ready"] == 0
    item = result["items"][0]
    assert item["rfq"]["status"] == "partial"
    assert item["rfq"]["work_item_key"] == "product:prd-1"
    assert item["rfq"]["rfq_and_quotes"]["rfq_draft_ready"] is True
    assert (
        item["rfq"]["rfq_and_quotes"]["three_accepted_quotes_ready"]
        is False
    )
    assert item["rfq"]["next"] == (
        "Collect and independently accept three exact-product quotes."
    )
    assert item["rfq"]["next_workspace"] == "/#sourcing"
    assert item["rfq"]["external_contact_allowed"] is False
    assert item["rfq"]["projection_authority"]["upstream_authority"] == (
        SOURCING_AUTHORITY
    )
    page_snapshots = item["rfq"]["projection_authority"][
        "page_snapshot_sha256"
    ]
    assert len(page_snapshots) == 1
    assert len(page_snapshots[0]) == 64


def test_workspace_reads_all_sourcing_pages_before_exact_product_mapping() -> None:
    sourcing_intelligence = PaginatedSourcingIntelligence()
    loop, _ = service(sourcing_intelligence=sourcing_intelligence)

    result = loop.workspace(
        principal=PRINCIPAL,
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=NOW,
    )

    assert sourcing_intelligence.cursors == [None, "page-2"]
    item = result["items"][0]
    assert item["rfq"]["work_item_key"] == "product:prd-1"
    assert item["rfq"]["rfq_and_quotes"]["rfq_draft_ready"] is True
    page_snapshots = item["rfq"]["projection_authority"][
        "page_snapshot_sha256"
    ]
    assert len(page_snapshots) == 2
    assert all(len(value) == 64 for value in page_snapshots)


def test_sourcing_projection_failure_is_visible_and_fails_closed() -> None:
    sourcing_intelligence = SourcingIntelligence(fail=True)
    loop, _ = service(sourcing_intelligence=sourcing_intelligence)

    result = loop.workspace(
        principal=PRINCIPAL,
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=NOW,
    )

    assert sourcing_intelligence.calls == 1
    assert result["status"] == "blocked"
    assert result["counts"]["rfq_blocked"] == 1
    item = result["items"][0]
    assert item["rfq"]["status"] == "blocked"
    assert "sourcing_intelligence_projection_failed" in item["source_gaps"]
    assert "rfq_product_work_item_not_found" in item["source_gaps"]
    assert item["rfq"]["external_contact_allowed"] is False


def test_missing_cost_evidence_never_becomes_profit_recommendation() -> None:
    loop, _ = service(complete=False)

    result = loop.workspace(
        principal=PRINCIPAL,
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=NOW,
    )

    profit = result["items"][0]["profit_recommendation"]
    assert profit["verdict"] == "awaiting_evidence"
    assert profit["unknown_costs"] == ["return"]
    assert profit["cm3_cny"] is None
    assert profit["ai_may_override"] is False


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_profit_values_never_become_recommendations(value: str) -> None:
    loop, _ = service()
    loop.sourcing_store.scenario.cm3_cny = Decimal(value)

    result = loop.workspace(
        principal=PRINCIPAL,
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=NOW,
    )

    profit = result["items"][0]["profit_recommendation"]
    assert profit["verdict"] == "awaiting_evidence"
    assert profit["cm3_cny"] is None
    assert result["counts"]["profit_recommended"] == 0


def test_complete_nonpositive_cm3_is_not_recommended() -> None:
    loop, _ = service(cm3="0.00")
    result = loop.workspace(
        principal=PRINCIPAL,
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=NOW,
    )
    assert result["items"][0]["profit_recommendation"]["verdict"] == "not_recommended"


def test_unbound_or_foreign_listing_fails_closed_without_supplier_link() -> None:
    loop, _ = service(bound=False)
    unbound = loop.workspace(
        principal=PRINCIPAL,
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=NOW,
        listing_ref="2216781923",
    )
    foreign = loop.workspace(
        principal=PRINCIPAL,
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=NOW,
        listing_ref="https://example.com/product/2216781923/",
    )

    assert unbound["items"] == []
    assert "marketplace_listing_canonical_product_unbound" in unbound["source_gaps"]
    assert foreign["items"] == []
    assert "listing_url_marketplace_not_supported" in foreign["source_gaps"]


def test_missing_catalog_readback_never_guesses_seller_offer_from_kjds_sku() -> None:
    loop, _ = service()
    loop.scoped_catalog = Catalog(
        items=[],
        status="no_data",
        source_gaps=["catalog_readback_missing"],
    )

    result = loop.workspace(
        principal=PRINCIPAL,
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=NOW,
    )

    assert result["items"][0]["identity"]["kjds_sku"] == "RU-001"
    assert result["items"][0]["listing"]["seller_offer_id"] is None
    assert result["items"][0]["listing"]["listing_url"] is None
    assert result["items"][0]["listing"]["binding_status"] == (
        "awaiting_catalog_readback"
    )


def test_specific_listing_lookup_never_falls_through_to_newer_sibling_listing() -> None:
    loop, _ = service()
    loop.scoped_catalog = Catalog(
        items=[
            {
                "offer_id": "RU-001-OLD",
                "marketplace_sku": "2216781923",
                "canonical_product_id": "prd-1",
                "observed_at": "2026-08-07T09:00:00+00:00",
                "source_evidence_id": "ev-old",
            },
            {
                "offer_id": "RU-001-NEW",
                "marketplace_sku": "2216781999",
                "canonical_product_id": "prd-1",
                "observed_at": "2026-08-08T09:00:00+00:00",
                "source_evidence_id": "ev-new",
            },
        ],
    )

    result = loop.workspace(
        principal=PRINCIPAL,
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=NOW,
        listing_ref="https://www.ozon.ru/product/storage-bag-2216781923/",
    )

    assert result["items"][0]["listing"]["marketplace_sku"] == "2216781923"
    assert result["items"][0]["listing"]["seller_offer_id"] == "RU-001-OLD"
    assert "multiple_current_marketplace_listings_for_product" not in result["source_gaps"]


def test_catalog_identity_cannot_be_resealed_for_two_canonical_products() -> None:
    loop, _ = service()
    loop.scoped_catalog = Catalog(
        items=[
            {
                "offer_id": "RU-SAME",
                "marketplace_sku": "2216781923",
                "canonical_product_id": "prd-1",
            },
            {
                "offer_id": "RU-SAME",
                "marketplace_sku": "2216781923",
                "canonical_product_id": "prd-2-canary",
            },
        ]
    )

    result = loop.workspace(
        principal=PRINCIPAL,
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=NOW,
    )

    assert result["status"] == "blocked"
    assert result["items"] == []
    assert "prd-2-canary" not in json.dumps(result)


def test_start_delegates_only_to_existing_ai_listing_internal_pipeline() -> None:
    loop, ai = service()
    result = loop.start(
        capture_submission_id="cap-1",
        selected_variant_key="sku:blue",
        store_ref="ozon-primary",
        as_of=NOW,
        idempotency_key="auto:cap-1:blue",
        principal=PRINCIPAL,
        entity_scope=SCOPE,
    )

    assert ai.create_args["mode"] == "internal_dry_run"
    assert ai.create_args["target_marketplace"] == "ozon"
    assert ai.process_args["run_id"] == "air-new"
    assert result["status"] == "evidence_review_required"
    assert result["automation_control"] == {
        "requested_mode": "manual_each_action",
        "effective_mode": "manual_each_action",
        "grant_ready": False,
        "runtime_execution_enabled": False,
        "preference_is_grant": False,
    }
    assert result["control_envelope"]["automation_runtime_connected"] is False
    assert result["control_envelope"]["automatic_internal_listing_progress"] is False
    assert result["control_envelope"]["automatic_supplier_order"] is False
    assert result["control_envelope"]["external_publish_requires_existing_approval_permit_readback"] is True


def test_scope_authority_fails_before_any_projection_or_internal_write() -> None:
    loop, ai = service()

    class UnreadableCatalog:
        def latest(self, **_kwargs):
            raise AssertionError("catalog must not be read")

    loop.scoped_catalog = UnreadableCatalog()
    invalid_scope = {"status": "ready", "entity_ref": "entity-1"}

    with pytest.raises(ValueError, match="current authority"):
        loop.workspace(
            principal=PRINCIPAL,
            entity_scope=invalid_scope,
            store_ref="ozon-primary",
            as_of=NOW,
        )
    with pytest.raises(ValueError, match="current authority"):
        loop.start(
            capture_submission_id="cap-1",
            selected_variant_key="sku:blue",
            store_ref="ozon-primary",
            as_of=NOW,
            idempotency_key="invalid-scope",
            principal=PRINCIPAL,
            entity_scope=invalid_scope,
        )

    assert ai.create_args is None
    assert ai.process_args is None


def test_automatic_mode_is_rejected_before_internal_listing_write() -> None:
    loop, ai = service()

    with pytest.raises(PermissionError, match="runtime is not connected"):
        loop.start(
            capture_submission_id="cap-1",
            selected_variant_key="sku:blue",
            store_ref="ozon-primary",
            as_of=NOW,
            idempotency_key="autonomous-not-admitted",
            principal=PRINCIPAL,
            entity_scope=SCOPE,
            requested_mode="policy_bound_autonomous",
        )

    assert ai.create_args is None
    assert ai.process_args is None


@pytest.mark.parametrize(
    "catalog",
    [
        Catalog(scope={**PROJECTED_SCOPE, "entity_ref": "scope-canary"}),
        Catalog(as_of="2026-08-07T10:00:00+00:00"),
        Catalog(snapshot_valid=False),
    ],
)
def test_catalog_scope_time_and_snapshot_drift_fail_closed(catalog) -> None:
    loop, _ = service()
    loop.scoped_catalog = catalog

    result = loop.workspace(
        principal=PRINCIPAL,
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=NOW,
        listing_ref="private-listing-canary",
    )

    assert result["status"] == "blocked"
    assert result["items"] == []
    assert result["lookup"]["input"] is None
    assert result["source_gaps"] == ["marketplace_catalog_projection_invalid"]
    assert "scope-canary" not in json.dumps(result)
    assert "private-listing-canary" not in json.dumps(result)


@pytest.mark.parametrize(
    "sourcing",
    [
        SourcingIntelligence(
            scope={**PROJECTED_SCOPE, "entity_ref": "scope-canary"}
        ),
        SourcingIntelligence(as_of="2026-08-07T10:00:00+00:00"),
        SourcingIntelligence(snapshot_valid=False),
        SourcingIntelligence(total_work_items=2),
    ],
)
def test_sourcing_scope_time_snapshot_and_hidden_page_fail_closed(sourcing) -> None:
    loop, _ = service(sourcing_intelligence=sourcing)

    result = loop.workspace(
        principal=PRINCIPAL,
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=NOW,
    )

    assert result["status"] == "blocked"
    assert result["counts"]["rfq_blocked"] == 1
    assert result["counts"]["rfq_drafts_ready"] == 0
    assert result["items"][0]["rfq"]["status"] == "blocked"
    assert result["items"][0]["rfq"]["external_contact_allowed"] is False
    assert "scope-canary" not in json.dumps(result)


def test_partial_sourcing_preserves_draft_but_not_three_quote_readiness() -> None:
    sourcing = SourcingIntelligence(
        status="partial",
        item_status="ready",
        source_gaps=["formal_quote_evidence_missing"],
    )
    loop, _ = service(sourcing_intelligence=sourcing)

    result = loop.workspace(
        principal=PRINCIPAL,
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=NOW,
    )

    rfq = result["items"][0]["rfq"]
    assert rfq["status"] == "partial"
    assert rfq["rfq_and_quotes"]["rfq_draft_ready"] is True
    assert rfq["rfq_and_quotes"]["three_accepted_quotes_ready"] is False
    assert result["counts"]["rfq_drafts_ready"] == 1
    assert result["counts"]["three_accepted_quotes_ready"] == 0


def test_invalid_upstream_reason_shape_fails_closed_without_canary_leak() -> None:
    sourcing = SourcingIntelligence(source_gaps=["PRIVATE CANARY VALUE"])
    loop, _ = service(sourcing_intelligence=sourcing)

    result = loop.workspace(
        principal=PRINCIPAL,
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=NOW,
    )

    serialized = json.dumps(result)
    assert result["status"] == "blocked"
    assert result["counts"]["rfq_drafts_ready"] == 0
    assert "PRIVATE CANARY VALUE" not in serialized


def test_sourcing_page_status_drift_fails_closed() -> None:
    sourcing = StatusDriftPaginatedSourcing()
    loop, _ = service(sourcing_intelligence=sourcing)

    result = loop.workspace(
        principal=PRINCIPAL,
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=NOW,
    )

    assert result["status"] == "blocked"
    assert result["counts"]["rfq_drafts_ready"] == 0
    assert "sourcing_intelligence_page_authority_mismatch" in result["source_gaps"]

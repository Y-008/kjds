from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.control_plane.scoped_pim import ScopedPimWorkspace
from apps.control_plane.security import Principal

AT = datetime(2026, 7, 29, 8, tzinfo=UTC)
SCOPE = {
    "status": "ready",
    "entity_ref": "entity-a",
    "authority_sha256": "a" * 64,
}


class Catalog:
    def __init__(self):
        self.calls = 0

    def latest(self, **_kwargs):
        self.calls += 1
        return {
            "contract_id": "kjds-scoped-marketplace-catalog-v1",
            "status": "ready",
            "as_of": AT.isoformat(),
            "scope": {
                "tenant_ref": "tenant-a",
                "entity_ref": "entity-a",
                "store_ref": "ozon-primary",
                "scope_grant_authority_sha256": "a" * 64,
            },
            "items": [
                {
                    "offer_id": "offer-1",
                    "sku": "market-sku-1",
                    "canonical_product_id": "product-1",
                    "item_hash": "1" * 64,
                    "source_evidence_id": "evidence-1",
                    "status": "active",
                },
                {
                    "offer_id": "offer-unbound",
                    "sku": "market-sku-x",
                    "canonical_product_id": None,
                    "item_hash": "2" * 64,
                    "source_evidence_id": "evidence-2",
                    "status": "active",
                },
            ],
            "source_gaps": [],
            "blockers": [],
            "snapshot_sha256": "3" * 64,
        }


class Content:
    def __init__(self):
        self.calls = 0

    def project_catalog(self, **_kwargs):
        self.calls += 1
        return {
            "contract_id": "kjds-scoped-product-content-v1",
            "status": "partial",
            "as_of": AT.isoformat(),
            "scope": {
                "tenant_ref": "tenant-a",
                "entity_ref": "entity-a",
                "store_ref": "ozon-primary",
                "scope_grant_authority_sha256": "a" * 64,
            },
            "products": [
                {
                    "product": {
                        "id": "product-1",
                        "sku": "CANON-1",
                        "name": "Canonical one",
                        "status": "active",
                    },
                    "source_lineage": {
                        "status": "observed",
                        "competitive_market_url": "https://www.ozon.ru/product/1/",
                        "primary_supplier_url": "https://detail.1688.com/offer/1.html",
                        "backup_supplier_urls": [],
                        "source_evidence_id": "evidence-source",
                        "authority": "product_event_ledger",
                        "links_are_observations_not_orders": True,
                        "external_sync_performed": False,
                    },
                    "passports": [{"kind": "quality", "status": "approved"}],
                    "content_assets": [],
                    "evidence_ids": ["evidence-1"],
                    "evidence_authority_sha256": "4" * 64,
                    "readiness": {
                        "product_identity_ready": True,
                        "passport_approved": True,
                        "media_qa_ready": False,
                        "content_draft_allowed": True,
                        "listing_draft_allowed": False,
                        "approval_plan_allowed": False,
                        "approval_created": False,
                        "permit_created": False,
                        "external_write_allowed": False,
                    },
                    "source_gaps": ["approved_media_qa_incomplete"],
                    "blockers": [],
                    "snapshot_sha256": "5" * 64,
                }
            ],
            "source_gaps": ["approved_media_qa_incomplete"],
            "blockers": [],
            "snapshot_sha256": "6" * 64,
        }


def principal(stores=frozenset({"ozon-primary"})):
    return Principal(
        actor_id="operator",
        roles=frozenset({"operator"}),
        tenant_ref="tenant-a",
        store_refs=stores,
    )


def test_missing_entity_never_reads_raw_authorities():
    catalog, content = Catalog(), Content()
    result = ScopedPimWorkspace(
        catalog=catalog, product_content=content
    ).project(
        principal=principal(),
        entity_scope={
            "status": "no_data",
            "reason": "entity_scope_authority_missing",
        },
        store_ref="ozon-primary",
        as_of=AT,
    )
    assert result["status"] == "no_data"
    assert result["control_envelope"]["scoped_input_read"] is False
    assert catalog.calls == content.calls == 0


def test_projects_canonical_group_unbound_listing_and_agent_limits():
    result = ScopedPimWorkspace(
        catalog=Catalog(), product_content=Content()
    ).project(
        principal=principal(),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=AT,
    )
    assert result["counts"] == {
        "total_product_groups": 1,
        "page_product_groups": 1,
        "bound_listings": 1,
        "unbound_listings": 1,
        "ready": 0,
        "incomplete": 1,
        "blocked": 0,
    }
    assert result["product_groups"][0]["product"]["id"] == "product-1"
    assert result["product_groups"][0]["source_lineage"][
        "primary_supplier_url"
    ] == "https://detail.1688.com/offer/1.html"
    assert result["unbound_listings"][0]["binding_issue"]
    assert result["control_envelope"]["client_recalculation_allowed"] is False
    assert result["agent_artifact"]["permit_issue_allowed"] is False
    assert result["control_envelope"]["external_write_allowed"] is False
    assert len(result["snapshot_sha256"]) == 64


def test_filter_and_cursor_are_deterministic_and_bad_cursor_fails():
    workspace = ScopedPimWorkspace(catalog=Catalog(), product_content=Content())
    first = workspace.project(
        principal=principal(),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=AT,
        query="canon",
        readiness="incomplete",
    )
    second = workspace.project(
        principal=principal(),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=AT,
        query="canon",
        readiness="incomplete",
    )
    assert first["snapshot_sha256"] == second["snapshot_sha256"]
    with pytest.raises(ValueError, match="cursor"):
        workspace.project(
            principal=principal(),
            entity_scope=SCOPE,
            store_ref="ozon-primary",
            as_of=AT,
            cursor="not-a-cursor",
        )


def test_counts_cover_the_filtered_result_not_only_the_current_page():
    content = Content()
    original = content.project_catalog

    def with_second_product(**kwargs):
        value = original(**kwargs)
        second = {
            **value["products"][0],
            "product": {
                **value["products"][0]["product"],
                "id": "product-2",
                "sku": "CANON-2",
                "name": "Canonical two",
            },
            "snapshot_sha256": "7" * 64,
        }
        value["products"] = [*value["products"], second]
        value["snapshot_sha256"] = "8" * 64
        return value

    content.project_catalog = with_second_product
    workspace = ScopedPimWorkspace(
        catalog=Catalog(), product_content=content
    )
    first = workspace.project(
        principal=principal(),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=AT,
        page_size=1,
    )
    assert first["counts"]["total_product_groups"] == 2
    assert first["counts"]["page_product_groups"] == 1
    assert first["counts"]["incomplete"] == 2
    assert first["query"]["next_cursor"]
    second = workspace.project(
        principal=principal(),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=AT,
        page_size=1,
        cursor=first["query"]["next_cursor"],
    )
    assert second["counts"]["total_product_groups"] == 2
    assert second["counts"]["page_product_groups"] == 1
    assert second["counts"]["incomplete"] == 2
    assert second["product_groups"][0]["product"]["id"] == "product-2"


def test_invalid_ready_scope_never_reads_raw_authorities():
    catalog, content = Catalog(), Content()
    result = ScopedPimWorkspace(
        catalog=catalog, product_content=content
    ).project(
        principal=principal(),
        entity_scope={
            "status": "ready",
            "entity_ref": "entity-a",
            "authority_sha256": None,
        },
        store_ref="ozon-primary",
        as_of=AT,
    )
    assert result["status"] == "blocked"
    assert result["scope"]["entity_ref"] is None
    assert result["source_gaps"] == [
        "pim_entity_scope_authority_invalid"
    ]
    assert result["control_envelope"]["scoped_input_read"] is False
    assert catalog.calls == content.calls == 0


def test_upstream_scope_or_contract_drift_fails_closed():
    catalog = Catalog()
    content = Content()
    original = catalog.latest

    def drifted(**kwargs):
        value = original(**kwargs)
        value["scope"] = {**value["scope"], "store_ref": "other-store"}
        value["contract_id"] = "unexpected-contract"
        return value

    catalog.latest = drifted
    result = ScopedPimWorkspace(
        catalog=catalog, product_content=content
    ).project(
        principal=principal(),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=AT,
    )
    assert result["status"] == "blocked"
    assert result["product_groups"] == []
    assert result["unbound_listings"] == []
    assert result["source_gaps"] == [
        "catalog_contract_conflict",
        "catalog_scope_conflict",
    ]
    assert result["control_envelope"]["external_write_allowed"] is False


def test_unauthorized_store_is_forbidden_before_any_read():
    with pytest.raises(PermissionError):
        ScopedPimWorkspace(catalog=Catalog(), product_content=Content()).project(
            principal=principal(),
            entity_scope=SCOPE,
            store_ref="other-store",
            as_of=AT,
        )

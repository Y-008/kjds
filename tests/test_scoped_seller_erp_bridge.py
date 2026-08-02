from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO

import pytest
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.control_plane.evidence import (
    EvidenceBlobRow,
    EvidenceService,
)
from apps.control_plane.evidence_scope import ScopedEvidenceAuthority
from apps.control_plane.scoped_seller_erp_bridge import (
    ScopedSellerErpBridge,
)
from apps.control_plane.security import Principal
from apps.control_plane.sql_repository import Base

SCOPE = {
    "status": "ready",
    "entity_ref": "entity-a",
    "authority_sha256": "a" * 64,
}
EXPORTED_AT = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()


def principal(
    actor_id: str,
    *roles: str,
    stores: frozenset[str] = frozenset({"ozon-primary"}),
) -> Principal:
    return Principal(
        actor_id=actor_id,
        roles=frozenset(roles or ("operator",)),
        tenant_ref="tenant-a",
        store_refs=stores,
    )


class Pim:
    def __init__(self):
        self.calls = 0

    def project(self, **kwargs):
        self.calls += 1
        at = kwargs["as_of"].isoformat()
        return {
            "contract_id": "kjds-native-scoped-pim-v1",
            "status": "ready",
            "as_of": at,
            "scope": {
                "tenant_ref": "tenant-a",
                "entity_ref": "entity-a",
                "store_ref": "ozon-primary",
                "scope_grant_authority_sha256": "a" * 64,
            },
            "product_groups": [
                {
                    "product": {
                        "id": "product-a",
                        "sku": "SKU-A",
                        "name": "Desk cable tray",
                        "status": "active",
                    },
                    "listings": [
                        {
                            "offer_id": "offer-a",
                            "marketplace_sku": "market-a",
                            "listing_status": "active",
                        }
                    ],
                },
                {
                    "product": {
                        "id": "product-b",
                        "sku": "SKU-B",
                        "name": "Canonical title",
                        "status": "active",
                    },
                    "listings": [
                        {
                            "offer_id": "offer-b",
                            "marketplace_sku": "market-b",
                            "listing_status": "active",
                        }
                    ],
                },
                {
                    "product": {
                        "id": "product-d",
                        "sku": "SKU-D",
                        "name": "Canonical only",
                        "status": "active",
                    },
                    "listings": [
                        {
                            "offer_id": "offer-d",
                            "marketplace_sku": "market-d",
                            "listing_status": "active",
                        }
                    ],
                },
            ],
            "snapshot_sha256": "1" * 64,
        }


class Oms:
    def __init__(self):
        self.calls = 0

    def workspace(self, **kwargs):
        self.calls += 1
        at = kwargs["as_of"].isoformat()
        return {
            "contract_id": "kjds-native-scoped-oms-v1",
            "status": "ready",
            "as_of": at,
            "scope": {
                "tenant_ref": "tenant-a",
                "entity_ref": "entity-a",
                "store_ref": "ozon-primary",
                "scope_grant_authority_sha256": "a" * 64,
            },
            "orders": [
                {
                    "external_id": "order-a",
                    "sku": "SKU-A",
                    "current_state": "paid",
                    "current_event": {
                        "quantity": 2,
                        "amount": "1000.00",
                        "currency": "RUB",
                        "effective_at": "2026-07-29T01:00:00+00:00",
                    },
                }
            ],
            "snapshot_sha256": "2" * 64,
        }


class Inventory:
    def __init__(self):
        self.calls = 0

    def workspace(self, **kwargs):
        self.calls += 1
        at = kwargs["as_of"].isoformat()
        return {
            "contract_id": (
                "kjds-native-scoped-inventory-fulfillment-v1"
            ),
            "status": "ready",
            "as_of": at,
            "scope": {
                "tenant_ref": "tenant-a",
                "entity_ref": "entity-a",
                "store_ref": "ozon-primary",
                "scope_grant_authority_sha256": "a" * 64,
            },
            "inventory_cells": [
                {
                    "projection_status": "ready",
                    "current_snapshot": {
                        "sku": "SKU-A",
                        "warehouse_ref": "warehouse-a",
                        "fulfillment_mode": "realFBS",
                        "quantities": {
                            "available_quantity": 5,
                            "reserved_quantity": 1,
                            "in_transit_quantity": 0,
                            "damaged_quantity": 0,
                            "quarantine_quantity": 0,
                        },
                        "effective_at": (
                            "2026-07-29T01:00:00+00:00"
                        ),
                    },
                }
            ],
            "snapshot_sha256": "3" * 64,
        }


class EvidenceNeverRead:
    def __getattr__(self, name):
        raise AssertionError(f"Evidence should not be read: {name}")


def workspace():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    evidence = EvidenceService(engine)
    pim, oms, inventory = Pim(), Oms(), Inventory()
    bridge = ScopedSellerErpBridge(
        evidence=evidence,
        scoped_evidence=ScopedEvidenceAuthority(evidence=evidence),
        pim=pim,
        oms=oms,
        inventory=inventory,
    )
    return engine, evidence, bridge, pim, oms, inventory


def catalog_csv(*rows: tuple[str, str, str, str, str]) -> bytes:
    lines = ["sku,offer,market,title,state"]
    lines.extend(",".join(row) for row in rows)
    return ("\n".join(lines) + "\n").encode()


CATALOG_MAP = {
    "seller_sku": "sku",
    "offer_id": "offer",
    "marketplace_sku": "market",
    "title": "title",
    "status": "state",
}


def submit_catalog(bridge, *, key="source-1", content=None):
    content = content or catalog_csv(
        (
            "SKU-A",
            "offer-a",
            "market-a",
            "Desk cable tray",
            "active",
        ),
        (
            "SKU-B",
            "offer-b",
            "market-b",
            "Seller title",
            "active",
        ),
        (
            "SKU-C",
            "offer-c",
            "market-c",
            "Source only",
            "active",
        ),
    )
    return bridge.submit_source(
        principal=principal("operator", "operator"),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        provider="dianxiaomi",
        source_kind="seller_erp_formal_export",
        domain="catalog",
        schema_version="seller-erp-bridge-catalog-v1",
        column_map=CATALOG_MAP,
        exported_at=EXPORTED_AT,
        authorization_mode="account_owner_export",
        authorization_evidence_id=None,
        effective_until=None,
        idempotency_key=key,
        content=content,
        filename="catalog.csv",
        content_type="text/csv",
    )


def authorize(bridge, source_id: str):
    review = bridge.review_source(
        principal=principal("reviewer", "reviewer"),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        source_evidence_id=source_id,
        accepted=True,
        authentic_original=True,
        authorization_verified=True,
        export_scope_matches=True,
        schema_mapping_verified=True,
        no_session_or_secret_material=True,
        rationale="Formal export and exact mapping independently checked.",
        effective_at=datetime.now(UTC).isoformat(),
        idempotency_key=f"review-{source_id}",
    )
    binding = bridge.bind_source(
        principal=principal("compliance", "compliance"),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        source_evidence_id=source_id,
        review_evidence_id=review["review_evidence_id"],
        effective_at=datetime.now(UTC).isoformat(),
        effective_until=None,
        idempotency_key=f"binding-{source_id}",
    )
    return review, binding


def test_missing_entity_or_source_reads_no_evidence_or_upstream():
    bridge = ScopedSellerErpBridge(
        evidence=EvidenceNeverRead(),
        scoped_evidence=EvidenceNeverRead(),
        pim=Pim(),
        oms=Oms(),
        inventory=Inventory(),
    )
    result = bridge.reconcile(
        principal=principal("operator"),
        entity_scope={
            "status": "no_data",
            "reason": "entity_scope_authority_missing",
        },
        store_ref="ozon-primary",
        as_of=datetime.now(UTC),
        source_evidence_id="evd-secret",
    )
    assert result["status"] == "no_data"
    assert result["diff_items"] == []
    assert result["control_envelope"]["scoped_input_read"] is False

    _, _, bridge, pim, oms, inventory = workspace()
    no_source = bridge.reconcile(
        principal=principal("operator"),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=datetime.now(UTC),
    )
    assert no_source["status"] == "no_data"
    assert pim.calls == oms.calls == inventory.calls == 0


def test_three_party_authority_and_catalog_diff_cover_all_states():
    _, _, bridge, pim, _, _ = workspace()
    source = submit_catalog(bridge)
    review, binding = authorize(
        bridge, source["source_evidence_id"]
    )
    result = bridge.reconcile(
        principal=principal("operator"),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=datetime.now(UTC),
        source_evidence_id=source["source_evidence_id"],
    )
    assert source["status"] == "pending_independent_review"
    assert review["status"] == "accepted_pending_compliance_binding"
    assert binding["three_party_independence"] is True
    assert result["status"] == "partial"
    assert result["counts"] == {
        "total_diff_items": 4,
        "page_diff_items": 4,
        "source_rows": 3,
        "canonical_rows": 3,
        "matched": 1,
        "source_only": 1,
        "canonical_only": 1,
        "conflict": 1,
        "blocked": 0,
    }
    assert {
        item["state"] for item in result["diff_items"]
    } == {"matched", "source_only", "canonical_only", "conflict"}
    conflict = next(
        item for item in result["diff_items"] if item["state"] == "conflict"
    )
    assert conflict["field_diffs"] == [
        {
            "field": "title",
            "source_value": "Seller title",
            "canonical_value": "Canonical title",
        }
    ]
    assert result["authority"]["three_party_independence"] is True
    assert result["agent_artifact"]["formal_fact_promotion_allowed"] is False
    assert result["control_envelope"]["external_write_allowed"] is False
    assert pim.calls == 1


def test_source_idempotency_conflict_and_three_party_separation():
    _, _, bridge, _, _, _ = workspace()
    first = submit_catalog(bridge)
    replay = submit_catalog(bridge)
    assert replay["source_evidence_id"] == first["source_evidence_id"]
    assert replay["idempotent_replay"] is True
    with pytest.raises(ValueError, match="idempotency"):
        submit_catalog(
            bridge,
            content=catalog_csv(
                ("SKU-Z", "offer-z", "market-z", "Changed", "active")
            ),
        )
    with pytest.raises(PermissionError, match="independent reviewer"):
        bridge.review_source(
            principal=principal("operator", "reviewer"),
            entity_scope=SCOPE,
            store_ref="ozon-primary",
            source_evidence_id=first["source_evidence_id"],
            accepted=True,
            authentic_original=True,
            authorization_verified=True,
            export_scope_matches=True,
            schema_mapping_verified=True,
            no_session_or_secret_material=True,
            rationale="self review must fail",
            effective_at=datetime.now(UTC).isoformat(),
            idempotency_key="self-review",
        )
    review, _ = authorize(bridge, first["source_evidence_id"])
    with pytest.raises(PermissionError, match="binding recorder"):
        bridge.bind_source(
            principal=principal("reviewer", "compliance"),
            entity_scope=SCOPE,
            store_ref="ozon-primary",
            source_evidence_id=first["source_evidence_id"],
            review_evidence_id=review["review_evidence_id"],
            effective_at=datetime.now(UTC).isoformat(),
            effective_until=None,
            idempotency_key="reviewer-cannot-bind",
        )


def test_latest_rejection_and_revocation_fail_closed_before_upstream():
    _, _, bridge, pim, _, _ = workspace()
    source = submit_catalog(bridge)
    authorize(bridge, source["source_evidence_id"])
    bridge.review_source(
        principal=principal("risk", "reviewer"),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        source_evidence_id=source["source_evidence_id"],
        accepted=False,
        authentic_original=False,
        authorization_verified=False,
        export_scope_matches=True,
        schema_mapping_verified=True,
        no_session_or_secret_material=True,
        rationale="New evidence invalidates the original authenticity claim.",
        effective_at=datetime.now(UTC).isoformat(),
        idempotency_key="latest-rejection",
    )
    rejected = bridge.reconcile(
        principal=principal("operator"),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=datetime.now(UTC),
        source_evidence_id=source["source_evidence_id"],
    )
    assert rejected["status"] == "blocked"
    assert rejected["diff_items"] == []
    assert any(
        "latest_review_invalid" in gap
        for gap in rejected["source_gaps"]
    )
    assert pim.calls == 0

    source2 = submit_catalog(bridge, key="source-2")
    authorize(bridge, source2["source_evidence_id"])
    bridge.revoke_source(
        principal=principal("compliance", "compliance"),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        source_evidence_id=source2["source_evidence_id"],
        reason="Account owner revoked this snapshot authorization.",
        effective_at=datetime.now(UTC).isoformat(),
        idempotency_key="revoke-source-2",
    )
    revoked = bridge.reconcile(
        principal=principal("operator"),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=datetime.now(UTC),
        source_evidence_id=source2["source_evidence_id"],
    )
    assert revoked["status"] == "blocked"
    assert "seller_erp_bridge_source_revoked" in revoked["source_gaps"]
    assert pim.calls == 0


def test_bad_source_evidence_and_unauthorized_store_fail_closed():
    engine, evidence, bridge, pim, _, _ = workspace()
    source = submit_catalog(bridge)
    authorize(bridge, source["source_evidence_id"])
    record = evidence.get(source["source_evidence_id"])
    with Session(engine) as session, session.begin():
        blob = session.get(EvidenceBlobRow, record.sha256)
        blob.content_bytes = b"tampered"
    result = bridge.reconcile(
        principal=principal("operator"),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=datetime.now(UTC),
        source_evidence_id=source["source_evidence_id"],
    )
    assert result["status"] == "blocked"
    assert result["diff_items"] == []
    assert pim.calls == 0
    with pytest.raises(PermissionError):
        bridge.reconcile(
            principal=principal(
                "operator", stores=frozenset({"other-store"})
            ),
            entity_scope=SCOPE,
            store_ref="ozon-primary",
            as_of=datetime.now(UTC),
            source_evidence_id=source["source_evidence_id"],
        )


def test_filters_cursor_and_snapshot_are_deterministic():
    _, _, bridge, _, _, _ = workspace()
    source = submit_catalog(bridge)
    authorize(bridge, source["source_evidence_id"])
    at = datetime.now(UTC)
    first = bridge.reconcile(
        principal=principal("operator"),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=at,
        source_evidence_id=source["source_evidence_id"],
        page_size=1,
        query="sku",
    )
    replay = bridge.reconcile(
        principal=principal("operator"),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=at,
        source_evidence_id=source["source_evidence_id"],
        page_size=1,
        query="sku",
    )
    assert first["snapshot_sha256"] == replay["snapshot_sha256"]
    assert first["query"]["next_cursor"]
    second = bridge.reconcile(
        principal=principal("operator"),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=at,
        source_evidence_id=source["source_evidence_id"],
        page_size=1,
        query="sku",
        cursor=first["query"]["next_cursor"],
    )
    assert (
        first["diff_items"][0]["canonical_key"]
        != second["diff_items"][0]["canonical_key"]
    )
    with pytest.raises(ValueError, match="cursor"):
        bridge.reconcile(
            principal=principal("operator"),
            entity_scope=SCOPE,
            store_ref="ozon-primary",
            as_of=at,
            source_evidence_id=source["source_evidence_id"],
            cursor="not-a-cursor",
        )


@pytest.mark.parametrize(
    ("domain", "schema_version", "column_map", "content", "expected_calls"),
    [
        (
            "orders",
            "seller-erp-bridge-orders-v1",
            {
                "order_external_id": "order",
                "seller_sku": "sku",
                "status": "state",
                "quantity": "qty",
                "gross_revenue": "revenue",
                "currency": "currency",
                "updated_at": "updated",
            },
            b"order,sku,state,qty,revenue,currency,updated\n"
            b"order-a,SKU-A,paid,2,1000.00,RUB,"
            b"2026-07-29T01:00:00Z\n",
            (0, 1, 0),
        ),
        (
            "inventory",
            "seller-erp-bridge-inventory-v1",
            {
                "seller_sku": "sku",
                "warehouse_ref": "warehouse",
                "fulfillment_mode": "mode",
                "available_quantity": "available",
                "reserved_quantity": "reserved",
                "in_transit_quantity": "transit",
                "damaged_quantity": "damaged",
                "quarantine_quantity": "quarantine",
                "updated_at": "updated",
            },
            b"sku,warehouse,mode,available,reserved,transit,damaged,"
            b"quarantine,updated\n"
            b"SKU-A,warehouse-a,realFBS,5,1,0,0,0,"
            b"2026-07-29T01:00:00Z\n",
            (0, 0, 1),
        ),
    ],
)
def test_order_and_inventory_domains_reconcile_without_creating_facts(
    domain,
    schema_version,
    column_map,
    content,
    expected_calls,
):
    _, _, bridge, pim, oms, inventory = workspace()
    source = bridge.submit_source(
        principal=principal("operator", "operator"),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        provider="official-export",
        source_kind="platform_official_export",
        domain=domain,
        schema_version=schema_version,
        column_map=column_map,
        exported_at=(datetime.now(UTC) - timedelta(minutes=5)).isoformat(),
        authorization_mode="first_party_account_export",
        authorization_evidence_id=None,
        effective_until=None,
        idempotency_key=f"{domain}-source",
        content=content,
        filename=f"{domain}.csv",
        content_type="text/csv",
    )
    authorize(bridge, source["source_evidence_id"])
    result = bridge.reconcile(
        principal=principal("operator"),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=datetime.now(UTC),
        source_evidence_id=source["source_evidence_id"],
    )
    assert result["status"] == "ready"
    assert result["counts"]["matched"] == 1
    assert (
        pim.calls,
        oms.calls,
        inventory.calls,
    ) == expected_calls
    assert result["control_envelope"]["formal_fact_promoted"] is False
    assert result["control_envelope"]["external_write_allowed"] is False


def test_schema_secret_columns_duplicate_keys_and_adapter_auth_fail():
    _, evidence, bridge, _, _, _ = workspace()
    with pytest.raises(ValueError, match="secret/session"):
        bridge.submit_source(
            principal=principal("operator"),
            entity_scope=SCOPE,
            store_ref="ozon-primary",
            provider="seller-tool",
            source_kind="seller_erp_formal_export",
            domain="catalog",
            schema_version="seller-erp-bridge-catalog-v1",
            column_map=CATALOG_MAP,
            exported_at=(
                datetime.now(UTC) - timedelta(minutes=5)
            ).isoformat(),
            authorization_mode="account_owner_export",
            authorization_evidence_id=None,
            effective_until=None,
            idempotency_key="secret-header",
            content=b"sku,offer,market,title,state,cookie\n"
            b"SKU-A,offer-a,market-a,title,active,secret\n",
            filename="catalog.csv",
            content_type="text/csv",
        )
    with pytest.raises(ValueError, match="duplicate canonical key"):
        submit_catalog(
            bridge,
            key="duplicates",
            content=catalog_csv(
                ("SKU-A", "offer-a", "market-a", "One", "active"),
                ("SKU-A", "offer-a", "market-a", "Two", "active"),
            ),
        )
    with pytest.raises(ValueError, match="authorization_evidence_id"):
        bridge.submit_source(
            principal=principal("operator"),
            entity_scope=SCOPE,
            store_ref="ozon-primary",
            provider="authorized-adapter",
            source_kind="authorized_adapter_snapshot",
            domain="catalog",
            schema_version="seller-erp-bridge-catalog-v1",
            column_map=CATALOG_MAP,
            exported_at=(
                datetime.now(UTC) - timedelta(minutes=5)
            ).isoformat(),
            authorization_mode="written_authorization",
            authorization_evidence_id=None,
            effective_until=None,
            idempotency_key="adapter-no-auth",
            content=catalog_csv(
                ("SKU-A", "offer-a", "market-a", "One", "active")
            ),
            filename="catalog.csv",
            content_type="text/csv",
        )
    assert evidence.list_by_source(
        ScopedSellerErpBridge.SOURCE_NAME
    ) == []


def test_xlsx_formal_export_freezes_worksheet_and_replays_same_diff():
    _, evidence, bridge, _, _, _ = workspace()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Catalog Export"
    sheet.append(["sku", "offer", "market", "title", "state"])
    sheet.append(
        [
            "SKU-A",
            "offer-a",
            "market-a",
            "Desk cable tray",
            "active",
        ]
    )
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()

    source = bridge.submit_source(
        principal=principal("operator", "operator"),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        provider="dianxiaomi",
        source_kind="seller_erp_formal_export",
        domain="catalog",
        schema_version="seller-erp-bridge-catalog-v1",
        column_map=CATALOG_MAP,
        exported_at=EXPORTED_AT,
        authorization_mode="account_owner_export",
        authorization_evidence_id=None,
        effective_until=None,
        idempotency_key="xlsx-source",
        content=buffer.getvalue(),
        filename="catalog.xlsx",
        content_type=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        worksheet="Catalog Export",
    )
    record = evidence.get(source["source_evidence_id"])
    assert record.metadata["worksheet"] == "Catalog Export"
    assert record.metadata["row_count"] == 1
    authorize(bridge, source["source_evidence_id"])
    result = bridge.reconcile(
        principal=principal("operator"),
        entity_scope=SCOPE,
        store_ref="ozon-primary",
        as_of=datetime.now(UTC),
        source_evidence_id=source["source_evidence_id"],
    )
    assert result["counts"]["matched"] == 1
    assert result["control_envelope"]["formal_fact_promoted"] is False

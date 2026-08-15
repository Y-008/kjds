from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from apps.control_plane.api import app
from apps.control_plane.batch_opportunity import BatchOpportunityWorkspace
from apps.control_plane.marketplace_observation import exact_candidate_key
from apps.control_plane.runtime import runtime
from apps.control_plane.scoped_batch_opportunity import (
    ScopedBatchOpportunityAuthority,
)
from apps.control_plane.security import AuthenticationFailure, Principal

AS_OF = datetime(2026, 7, 28, 6, 0, tzinfo=UTC)
AUTHORITY_HASH = "a" * 64
PRODUCT_IDENTITY = {
    "category": "cable-wrap",
    "manufacturer_part_number": "CW-001",
}


def candidate_key(variant_key: str) -> str:
    value = exact_candidate_key(PRODUCT_IDENTITY, variant_key)
    assert value is not None
    return value


def principal(*, stores: frozenset[str] | None = None) -> Principal:
    return Principal(
        "operator-a",
        frozenset({"operator"}),
        "tenant-a",
        stores or frozenset({"store-a"}),
    )


def entity_scope() -> dict:
    return {
        "status": "ready",
        "entity_ref": "entity-a",
        "authority_sha256": AUTHORITY_HASH,
    }


def observation(
    *,
    item_id: str,
    candidate_key: str,
    marketplace: str,
    variant_key: str,
    price: str,
    currency: str,
    supplier_ref: str | None,
    source_grade: str = "C",
    external_item_id: str | None = None,
    target_product_id: str | None = None,
    target_offer_id: str | None = None,
    observed_quantity: int = 1,
    min_order_quantity: int = 1,
    checkout_verified: bool = False,
    purchase_available: bool = False,
    observed_at: datetime | None = None,
) -> dict:
    return {
        "id": item_id,
        "snapshot_id": f"snapshot-{item_id}",
        "fingerprint": f"fingerprint-{item_id}",
        "marketplace": marketplace,
        "store_ref": "store-a",
        "external_item_id": external_item_id or item_id,
        "supplier_ref": supplier_ref,
        "title": f"title-{item_id}",
        "variant_key": variant_key,
        "currency": currency,
        "displayed_price": price,
        "unit_price": price,
        "price_kind": (
            "marketplace_listing_price"
            if marketplace == "ozon"
            else "observed_checkout_price"
        ),
        "min_order_quantity": min_order_quantity,
        "target_product_id": target_product_id,
        "target_offer_id": target_offer_id,
        "source_url": (
            f"https://ozon.ru/product/{item_id}"
            if marketplace == "ozon"
            else f"https://detail.1688.com/offer/{item_id}.html"
        ),
        "observed_at": (
            observed_at or (AS_OF - timedelta(hours=2))
        ).isoformat(),
        "evidence_id": f"evidence-{item_id}",
        "candidate_key": candidate_key,
        "product_identity": PRODUCT_IDENTITY,
        "observed_quantity": observed_quantity,
        "checkout_verified": checkout_verified,
        "purchase_available": purchase_available,
        "confidence": "0.90",
        "market_signals": {"promotion": False},
        "source_grade": source_grade,
        "semantic_authority": (
            "external_market_observation_only"
            if marketplace == "ozon"
            else "supplier_market_observation_only"
        ),
    }


class ObservationAuthority:
    def __init__(self, *, ozon: list[dict], suppliers: list[dict]):
        self.rows = {"ozon": ozon, "1688": suppliers}
        self.calls: list[str] = []

    def collect(self, *, marketplace: str, **_values) -> dict:
        self.calls.append(marketplace)
        items = self.rows[marketplace]
        return {
            "status": "ready" if items else "no_data",
            "items": items,
            "source_gaps": [] if items else ["observation_not_available"],
            "blockers": [],
            "pagination": {"truncated": False},
            "snapshot_sha256": (
                "1" * 64 if marketplace == "ozon" else "2" * 64
            ),
        }


class CatalogAuthority:
    def __init__(self, items: list[dict]):
        self.items = items
        self.calls = 0

    def latest(self, **_values) -> dict:
        self.calls += 1
        return {
            "status": "ready" if self.items else "no_data",
            "items": self.items,
            "source_gaps": [] if self.items else ["catalog_not_available"],
            "blockers": [],
            "snapshot_sha256": "3" * 64,
        }


def authority(
    *,
    ozon: list[dict],
    suppliers: list[dict],
    catalog: list[dict] | None = None,
) -> tuple[
    ScopedBatchOpportunityAuthority,
    ObservationAuthority,
    CatalogAuthority,
]:
    observations = ObservationAuthority(ozon=ozon, suppliers=suppliers)
    catalog_authority = CatalogAuthority(catalog or [])
    return (
        ScopedBatchOpportunityAuthority(
            batch=BatchOpportunityWorkspace,
            scoped_observations=observations,
            scoped_catalog=catalog_authority,
            scoped_evidence=object(),
            rules=object(),
        ),
        observations,
        catalog_authority,
    )


def test_market_radar_groups_exact_identity_and_separates_own_listing():
    first = candidate_key("black-3-pack")
    second = candidate_key("red-3-pack")
    ozon = [
        observation(
            item_id="own",
            candidate_key=first,
            marketplace="ozon",
            variant_key="black-3-pack",
            price="1000.00",
            currency="RUB",
            supplier_ref=None,
            external_item_id="own-offer",
        ),
        observation(
            item_id="competitor-1",
            candidate_key=first,
            marketplace="ozon",
            variant_key="black-3-pack",
            price="1100.00",
            currency="RUB",
            supplier_ref="seller-1",
        ),
        observation(
            item_id="competitor-2",
            candidate_key=first,
            marketplace="ozon",
            variant_key="black-3-pack",
            price="1200.00",
            currency="RUB",
            supplier_ref="seller-2",
        ),
        observation(
            item_id="competitor-red",
            candidate_key=second,
            marketplace="ozon",
            variant_key="red-3-pack",
            price="900.00",
            currency="RUB",
            supplier_ref="seller-3",
        ),
    ]
    suppliers = [
        observation(
            item_id="supplier-3-a",
            candidate_key=first,
            marketplace="1688",
            variant_key="black-3-pack",
            price="200.00",
            currency="CNY",
            supplier_ref="supplier-a",
            observed_quantity=3,
            checkout_verified=True,
            purchase_available=True,
        ),
        observation(
            item_id="supplier-3-a-second-row",
            candidate_key=first,
            marketplace="1688",
            variant_key="black-3-pack",
            price="210.00",
            currency="CNY",
            supplier_ref="supplier-a",
            observed_quantity=3,
            checkout_verified=True,
            purchase_available=True,
        ),
        observation(
            item_id="supplier-100-b",
            candidate_key=first,
            marketplace="1688",
            variant_key="black-3-pack",
            price="150.00",
            currency="CNY",
            supplier_ref="supplier-b",
            observed_quantity=100,
            min_order_quantity=100,
            checkout_verified=True,
            purchase_available=True,
        ),
        observation(
            item_id="supplier-red",
            candidate_key=second,
            marketplace="1688",
            variant_key="red-3-pack",
            price="180.00",
            currency="CNY",
            supplier_ref="supplier-c",
            observed_quantity=3,
            checkout_verified=True,
            purchase_available=True,
        ),
    ]
    service, _, _ = authority(
        ozon=ozon,
        suppliers=suppliers,
        catalog=[
            {
                "offer_id": "own-offer",
                "canonical_product_id": "product-own",
            }
        ],
    )

    result = service.market_radar(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
        target_purchase_quantity=3,
    )

    assert result["status"] == "ready"
    assert result["counts"] == {
        "observed_listings": 8,
        "evidence_bound_rows": 8,
        "eligible_exact_rows": 8,
        "unique_exact_identities": 2,
        "own_listing_rows": 1,
        "competitor_listing_rows": 3,
        "unique_competitor_sellers": 3,
        "supplier_option_rows": 4,
        "unique_supplier_identities": 3,
        "checkout_comparable_at_target": 3,
        "unresolved_or_filtered_rows": 0,
        "stale_rows": 0,
        "disallowed_grade_rows": 0,
    }
    black = next(
        item
        for item in result["cohorts"]
        if item["candidate_key"] == first
    )
    assert black["counts"]["own_listing_rows"] == 1
    assert black["counts"]["competitor_listing_rows"] == 2
    assert black["counts"]["unique_supplier_identities"] == 2
    assert black["counts"]["checkout_comparable_at_target"] == 2
    assert black["supplier_alternative_rows"] == 1
    assert black["competitor_price_bands"][0][
        "price_distribution"
    ]["median"] == "1200.00"
    assert black["supplier_price_bands_at_target"][0][
        "price_distribution"
    ]["minimum"] == "200.00"
    assert black["own_listing_current_facts"][0]["unit_price"] == "1000.00"
    assert result["control_envelope"]["sales_inferred"] is False
    assert result["control_envelope"]["external_write_allowed"] is False


def test_market_radar_keeps_variants_and_currencies_separate():
    first = candidate_key("black")
    second = candidate_key("red")
    ozon = [
        observation(
            item_id="black-rub",
            candidate_key=first,
            marketplace="ozon",
            variant_key="black",
            price="900.00",
            currency="RUB",
            supplier_ref="seller-1",
        ),
        observation(
            item_id="black-cny",
            candidate_key=first,
            marketplace="ozon",
            variant_key="black",
            price="70.00",
            currency="CNY",
            supplier_ref="seller-2",
        ),
        observation(
            item_id="red-rub",
            candidate_key=second,
            marketplace="ozon",
            variant_key="red",
            price="950.00",
            currency="RUB",
            supplier_ref="seller-3",
        ),
    ]
    suppliers = [
        observation(
            item_id=f"supplier-{key[0]}",
            candidate_key=key,
            marketplace="1688",
            variant_key=variant,
            price="100.00",
            currency="CNY",
            supplier_ref=f"supplier-{key[0]}",
            observed_quantity=3,
            checkout_verified=True,
            purchase_available=True,
        )
        for key, variant in ((first, "black"), (second, "red"))
    ]
    service, _, _ = authority(ozon=ozon, suppliers=suppliers)

    result = service.market_radar(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )

    assert result["counts"]["unique_exact_identities"] == 2
    black = next(
        item
        for item in result["cohorts"]
        if item["variant_key"] == "black"
    )
    assert [item["currency"] for item in black["competitor_price_bands"]] == [
        "CNY",
        "RUB",
    ]
    assert result["query"]["currency_conversion_performed"] is False


def test_market_radar_discloses_stale_and_disallowed_grade_without_scoring():
    key = candidate_key("black")
    ozon = [
        observation(
            item_id="stale",
            candidate_key=key,
            marketplace="ozon",
            variant_key="black",
            price="900.00",
            currency="RUB",
            supplier_ref="seller-1",
            observed_at=AS_OF - timedelta(days=30),
        ),
        observation(
            item_id="grade-d",
            candidate_key=key,
            marketplace="ozon",
            variant_key="black",
            price="800.00",
            currency="RUB",
            supplier_ref="seller-2",
            source_grade="D",
        ),
    ]
    service, _, _ = authority(ozon=ozon, suppliers=[])

    result = service.market_radar(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
        source_grades=("A", "B", "C"),
        max_age_hours=24,
    )

    assert result["status"] == "no_data"
    assert result["counts"]["unique_exact_identities"] == 0
    assert result["counts"]["stale_rows"] == 1
    assert result["counts"]["disallowed_grade_rows"] == 1
    assert result["unresolved"]["by_reason"] == {
        "observation_stale": 1,
        "source_grade_not_accepted": 1,
    }
    assert "market_radar_observation_stale" in result["source_gaps"]
    assert result["control_envelope"]["candidate_scoring_performed"] is False


def test_market_radar_rejects_candidate_key_that_does_not_match_identity():
    service, _, _ = authority(
        ozon=[
            observation(
                item_id="tampered-key",
                candidate_key="f" * 64,
                marketplace="ozon",
                variant_key="black",
                price="900.00",
                currency="RUB",
                supplier_ref="seller-1",
            )
        ],
        suppliers=[],
    )

    result = service.market_radar(
        principal=principal(),
        entity_scope=entity_scope(),
        store_ref="store-a",
        as_of=AS_OF,
    )

    assert result["status"] == "no_data"
    assert result["unresolved"]["by_reason"] == {
        "candidate_key_identity_variant_mismatch": 1
    }
    assert result["counts"]["eligible_exact_rows"] == 0


def test_market_radar_missing_entity_authority_performs_no_child_reads():
    service, observations, catalog = authority(ozon=[], suppliers=[])

    result = service.market_radar(
        principal=principal(),
        entity_scope={
            "status": "no_data",
            "entity_ref": None,
            "authority_sha256": None,
            "reason": "entity_scope_authority_missing",
        },
        store_ref="store-a",
        as_of=AS_OF,
    )

    assert result["status"] == "no_data"
    assert result["scope"]["entity_ref"] is None
    assert observations.calls == []
    assert catalog.calls == 0
    assert result["control_envelope"]["external_write_allowed"] is False


def test_market_radar_is_deterministic_and_rejects_scope_or_bad_query():
    key = candidate_key("black")
    service, _, _ = authority(
        ozon=[
            observation(
                item_id="competitor",
                candidate_key=key,
                marketplace="ozon",
                variant_key="black",
                price="900.00",
                currency="RUB",
                supplier_ref="seller-1",
            )
        ],
        suppliers=[
            observation(
                item_id="supplier",
                candidate_key=key,
                marketplace="1688",
                variant_key="black",
                price="100.00",
                currency="CNY",
                supplier_ref="supplier-1",
                observed_quantity=3,
                checkout_verified=True,
                purchase_available=True,
            )
        ],
    )
    values = {
        "principal": principal(),
        "entity_scope": entity_scope(),
        "store_ref": "store-a",
        "as_of": AS_OF,
    }

    first = service.market_radar(**values)
    second = service.market_radar(**values)
    assert first["snapshot_sha256"] == second["snapshot_sha256"]
    with pytest.raises(PermissionError):
        service.market_radar(**{**values, "store_ref": "store-b"})
    with pytest.raises(ValueError, match="timezone"):
        service.market_radar(**values, timezone="Mars/Olympus")
    with pytest.raises(ValueError, match="source grades"):
        service.market_radar(**values, source_grades=("Z",))


def test_market_radar_api_is_authenticated_scoped_and_in_openapi(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _key: principal(),
    )
    monkeypatch.setattr(
        runtime.scope_grants,
        "current",
        lambda **_values: entity_scope(),
    )

    def fake_radar(**values):
        captured.update(values)
        return {
            "contract_id": "kjds-scoped-market-radar-v1",
            "status": "no_data",
            "scope": {
                "tenant_ref": "tenant-a",
                "entity_ref": "entity-a",
                "store_ref": "store-a",
            },
            "counts": {},
            "cohorts": [],
            "control_envelope": {"external_write_allowed": False},
        }

    monkeypatch.setattr(
        runtime.scoped_batch_opportunity,
        "market_radar",
        fake_radar,
    )
    client = TestClient(app)
    response = client.get(
        "/v1/market-radar",
        params={
            "store_ref": "store-a",
            "source_grades": "A,C",
            "target_purchase_quantity": 3,
        },
        headers={"X-KJDS-API-Key": "test-key"},
    )
    forbidden = client.get(
        "/v1/market-radar",
        params={"store_ref": "store-b"},
        headers={"X-KJDS-API-Key": "test-key"},
    )

    assert response.status_code == 200
    assert captured["source_grades"] == ("A", "C")
    assert captured["target_purchase_quantity"] == 3
    assert forbidden.status_code == 403
    operation = app.openapi()["paths"]["/v1/market-radar"]["get"]
    assert operation["security"] == [{"KjdsApiKey": []}]


def test_market_radar_api_rejects_anonymous(monkeypatch):
    def reject(_key):
        raise AuthenticationFailure("X-KJDS-API-Key is required", 401)

    monkeypatch.setattr(runtime.authenticator, "authenticate", reject)
    response = TestClient(app).get(
        "/v1/market-radar",
        params={"store_ref": "store-a"},
    )
    assert response.status_code == 401

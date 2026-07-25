import base64
import hashlib
import json
from types import SimpleNamespace

import pytest

from apps.control_plane.marketplace_catalog import (
    EXTERNAL_MEDIA_RIGHTS_STATUS,
    InMemoryMarketplaceCatalogStore,
    MarketplaceCatalogWorkspace,
    parse_ozon_product_bundle,
)


def response(path, body):
    encoded = json.dumps(body, separators=(",", ":")).encode()
    return {
        "path": path,
        "status_code": 200,
        "headers": {},
        "body_sha256": hashlib.sha256(encoded).hexdigest(),
        "body_base64": base64.b64encode(encoded).decode(),
    }


def product_bundle(*, offer_id="offer-1", price="1299.00", present=7):
    info = {
        "items": [
            {
                "offer_id": offer_id,
                "sku": 321,
                "name": "Verified seller item",
                "currency_code": "RUB",
                "price": price,
                "old_price": "1499.00",
                "stocks": {
                    "has_stock": present > 0,
                    "stocks": [{"present": present, "reserved": 1, "type": "fbs"}],
                },
                "statuses": {"is_created": True},
                "images": ["https://cdn.example/item-main.jpg"],
                "primary_image": ["https://cdn.example/item-primary.jpg"],
            }
        ]
    }
    attributes = {
        "result": [
            {
                "offer_id": offer_id,
                "sku": 321,
                "name": "Verified seller item",
                "width": 12,
                "height": 8,
                "depth": 4,
                "dimension_unit": "mm",
                "weight": 300,
                "weight_unit": "g",
                "attributes": [{"id": 1, "values": [{"value": "blue"}]}],
                "attributes_with_defaults": [],
                "complex_attributes": [
                    {
                        "attributes": [
                            {
                                "id": 2,
                                "video_url": "https://video.example/item.mp4",
                            }
                        ]
                    }
                ],
                "images": ["https://cdn.example/item-detail.jpg"],
                "pdf_list": [{"name": "manual", "url": "https://cdn.example/manual.pdf"}],
            }
        ]
    }
    return json.dumps(
        {
            "schema_version": "ozon-response-bundle-v2",
            "contract_version": "ozon-product-read-v1",
            "responses": [
                response("/v3/product/info/list", info),
                response("/v4/product/info/attributes", attributes),
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


class EvidenceSpy:
    def __init__(self):
        self.links = []

    def link(self, **kwargs):
        self.links.append(kwargs)


def workspace(*, bundles):
    records = {
        evidence_id: (
            content,
            SimpleNamespace(effective_at=f"2026-07-{20 + index:02d}T00:00:00+00:00"),
        )
        for index, (evidence_id, content) in enumerate(bundles.items())
    }
    evidence = EvidenceSpy()
    return (
        MarketplaceCatalogWorkspace(
            verified_bundle_loader=lambda evidence_id: records[evidence_id],
            store=InMemoryMarketplaceCatalogStore(),
            evidence=evidence,
        ),
        evidence,
    )


def test_verified_ozon_bundle_normalizes_catalog_and_media_references():
    item = parse_ozon_product_bundle(
        product_bundle(),
        source_evidence_id="evd-1",
        observed_at="2026-07-20T00:00:00+00:00",
    )

    assert item["offer_id"] == "offer-1"
    assert item["marketplace_sku"] == "321"
    assert item["available_stock"] == 7
    assert item["prices"]["price"] == "1299.00"
    assert len(item["image_references"]) == 3
    assert item["video_references"] == ["https://video.example/item.mp4"]
    assert item["document_references"] == [
        "https://cdn.example/manual.pdf",
        "manual",
    ]
    assert item["media_rights_status"] == EXTERNAL_MEDIA_RIGHTS_STATUS
    assert len(item["item_hash"]) == 64


def test_catalog_workspace_is_idempotent_and_selects_latest_item():
    catalog, evidence = workspace(
        bundles={
            "evd-1": product_bundle(price="1299.00", present=7),
            "evd-2": product_bundle(price="1199.00", present=9),
        }
    )
    first = catalog.import_ozon_evidence(
        evidence_ids=["evd-1"],
        store_ref="store-main",
        idempotency_key="catalog-1",
        imported_by="operator-1",
    )
    replay = catalog.import_ozon_evidence(
        evidence_ids=["evd-1"],
        store_ref="store-main",
        idempotency_key="catalog-1",
        imported_by="operator-1",
    )
    catalog.import_ozon_evidence(
        evidence_ids=["evd-2"],
        store_ref="store-main",
        idempotency_key="catalog-2",
        imported_by="operator-1",
    )

    assert replay["id"] == first["id"]
    assert len(evidence.links) == 3
    latest = catalog.latest_items(store_ref="store-main")
    assert len(latest) == 1
    assert latest[0]["prices"]["price"] == "1199.00"
    assert latest[0]["available_stock"] == 9


def test_catalog_workspace_rejects_idempotency_conflict():
    catalog, _ = workspace(
        bundles={
            "evd-1": product_bundle(price="1299.00"),
            "evd-2": product_bundle(price="1199.00"),
        }
    )
    catalog.import_ozon_evidence(
        evidence_ids=["evd-1"],
        store_ref="store-main",
        idempotency_key="same-key",
        imported_by="operator-1",
    )
    with pytest.raises(ValueError, match="idempotency conflict"):
        catalog.import_ozon_evidence(
            evidence_ids=["evd-2"],
            store_ref="store-main",
            idempotency_key="same-key",
            imported_by="operator-1",
        )


@pytest.mark.parametrize("mutation", ["body_hash", "target_mismatch", "duplicate_path"])
def test_catalog_parser_fails_closed_on_contract_drift(mutation):
    payload = json.loads(product_bundle())
    if mutation == "body_hash":
        payload["responses"][0]["body_sha256"] = "0" * 64
    elif mutation == "duplicate_path":
        payload["responses"][1]["path"] = payload["responses"][0]["path"]
    else:
        body = json.loads(
            base64.b64decode(payload["responses"][1]["body_base64"])
        )
        body["result"][0]["offer_id"] = "different"
        payload["responses"][1] = response(
            "/v4/product/info/attributes",
            body,
        )

    with pytest.raises(ValueError):
        parse_ozon_product_bundle(
            json.dumps(payload).encode(),
            source_evidence_id="evd-1",
            observed_at="2026-07-20T00:00:00+00:00",
        )

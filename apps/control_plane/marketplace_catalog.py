from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from .domain import new_id

OZON_PRODUCT_BUNDLE_SCHEMA = "ozon-response-bundle-v2"
OZON_PRODUCT_CONTRACT_VERSION = "ozon-product-read-v1"
OZON_PRODUCT_PATHS = frozenset(
    {"/v3/product/info/list", "/v4/product/info/attributes"}
)
EXTERNAL_MEDIA_RIGHTS_STATUS = "unverified_external_reference"


def _canonical_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _required_text(value: Any, field: str, *, max_length: int) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"Ozon catalog item requires {field}")
    if len(normalized) > max_length:
        raise ValueError(f"Ozon catalog item {field} exceeds {max_length} characters")
    return normalized


def _optional_text(value: Any, *, max_length: int) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    if len(normalized) > max_length:
        raise ValueError(f"Ozon catalog text exceeds {max_length} characters")
    return normalized


def _json_body(response: dict[str, Any]) -> dict[str, Any]:
    if response.get("status_code") != 200:
        raise ValueError("Ozon product response must have status 200")
    encoded = response.get("body_base64")
    declared_hash = response.get("body_sha256")
    if not isinstance(encoded, str) or not isinstance(declared_hash, str):
        raise ValueError("Ozon product response body contract is incomplete")
    try:
        body_bytes = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("Ozon product response body is not valid base64") from exc
    actual_hash = hashlib.sha256(body_bytes).hexdigest()
    if actual_hash != declared_hash:
        raise ValueError("Ozon product response body hash does not match")
    try:
        body = json.loads(body_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Ozon product response body is not valid JSON") from exc
    if not isinstance(body, dict):
        raise ValueError("Ozon product response body must be an object")
    return body


def _single_object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise ValueError(f"Ozon product response must contain exactly one {field} item")
    return value[0]


def _string_leaves(value: Any) -> list[str]:
    if isinstance(value, str):
        normalized = value.strip()
        return [normalized] if normalized else []
    if isinstance(value, list):
        return [leaf for item in value for leaf in _string_leaves(item)]
    if isinstance(value, dict):
        return [leaf for item in value.values() for leaf in _string_leaves(item)]
    return []


def _media_references(
    info: dict[str, Any], attributes: dict[str, Any]
) -> tuple[list[str], list[str], list[str]]:
    image_keys = (
        "images",
        "images360",
        "primary_image",
        "color_image",
    )
    pdf_keys = ("pdf_list", "pdf", "documents")
    images = sorted(
        {
            leaf
            for source in (info, attributes)
            for key in image_keys
            for leaf in _string_leaves(source.get(key))
        }
    )
    pdfs = sorted(
        {
            leaf
            for source in (info, attributes)
            for key in pdf_keys
            for leaf in _string_leaves(source.get(key))
        }
    )

    videos: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if "video" in str(key).lower():
                    videos.update(_string_leaves(child))
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(attributes.get("complex_attributes", []))
    visit(attributes.get("attributes", []))
    visit(info)
    videos.update(
        leaf
        for leaf in _string_leaves(attributes.get("complex_attributes", []))
        if leaf.lower().split("?", 1)[0].endswith((".mp4", ".mov", ".webm"))
    )
    return images, sorted(videos), pdfs


def _normalized_stocks(info: dict[str, Any]) -> list[dict[str, Any]]:
    value = info.get("stocks")
    if isinstance(value, dict):
        value = value.get("stocks")
    if not isinstance(value, list):
        return []
    return [stock for stock in value if isinstance(stock, dict)]


def _available_stock(stocks: list[dict[str, Any]]) -> int | None:
    total = 0
    found = False
    for stock in stocks:
        present = stock.get("present")
        if isinstance(present, bool):
            continue
        if isinstance(present, int) and present >= 0:
            total += present
            found = True
    return total if found else None


def parse_ozon_product_bundle(
    content: bytes,
    *,
    source_evidence_id: str,
    observed_at: str,
) -> dict[str, Any]:
    try:
        bundle = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Ozon product Evidence is not valid JSON") from exc
    if not isinstance(bundle, dict):
        raise ValueError("Ozon product Evidence bundle must be an object")
    if bundle.get("schema_version") != OZON_PRODUCT_BUNDLE_SCHEMA:
        raise ValueError("Ozon product Evidence has an unsupported bundle schema")
    if bundle.get("contract_version") != OZON_PRODUCT_CONTRACT_VERSION:
        raise ValueError("Ozon product Evidence has an unsupported contract version")
    responses = bundle.get("responses")
    if not isinstance(responses, list) or len(responses) != len(OZON_PRODUCT_PATHS):
        raise ValueError("Ozon product Evidence must contain the bound response pair")
    by_path: dict[str, dict[str, Any]] = {}
    for response in responses:
        if not isinstance(response, dict):
            raise ValueError("Ozon product response entry must be an object")
        path = response.get("path")
        if path not in OZON_PRODUCT_PATHS or path in by_path:
            raise ValueError("Ozon product Evidence contains an unsupported response path")
        by_path[path] = _json_body(response)
    if frozenset(by_path) != OZON_PRODUCT_PATHS:
        raise ValueError("Ozon product Evidence response paths are incomplete")

    info = _single_object(by_path["/v3/product/info/list"].get("items"), "info")
    attributes = _single_object(
        by_path["/v4/product/info/attributes"].get("result"), "attribute"
    )
    offer_id = _required_text(info.get("offer_id"), "offer_id", max_length=160)
    attribute_offer_id = _required_text(
        attributes.get("offer_id"), "attribute offer_id", max_length=160
    )
    if offer_id != attribute_offer_id:
        raise ValueError("Ozon product response targets do not match")

    marketplace_sku = _optional_text(
        info.get("sku") or attributes.get("sku"), max_length=160
    )
    name = _required_text(
        info.get("name") or attributes.get("name"), "name", max_length=500
    )
    images, videos, pdfs = _media_references(info, attributes)
    stocks = _normalized_stocks(info)
    prices = {
        key: info[key]
        for key in (
            "price",
            "old_price",
            "min_price",
            "marketing_price",
            "marketing_seller_price",
            "auto_action_enabled",
        )
        if key in info
    }
    statuses = {
        key: info[key]
        for key in (
            "statuses",
            "status",
            "visibility_details",
            "errors",
            "availabilities",
        )
        if key in info
    }
    dimensions = {
        key: attributes[key]
        for key in (
            "depth",
            "height",
            "width",
            "dimension_unit",
            "weight",
            "weight_unit",
        )
        if key in attributes
    }
    if "volume_weight" in info:
        dimensions["volume_weight"] = info["volume_weight"]

    item = {
        "offer_id": offer_id,
        "marketplace_sku": marketplace_sku,
        "name": name,
        "currency_code": _optional_text(
            info.get("currency_code"), max_length=12
        ),
        "prices": prices,
        "available_stock": _available_stock(stocks),
        "stocks": stocks,
        "statuses": statuses,
        "dimensions": dimensions,
        "attributes": attributes.get("attributes", []),
        "attributes_with_defaults": attributes.get(
            "attributes_with_defaults", []
        ),
        "complex_attributes": attributes.get("complex_attributes", []),
        "image_references": images,
        "video_references": videos,
        "document_references": pdfs,
        "media_rights_status": EXTERNAL_MEDIA_RIGHTS_STATUS,
        "source_evidence_id": source_evidence_id,
        "observed_at": observed_at,
        "canonical_product_id": None,
    }
    return {**item, "item_hash": _canonical_hash(item)}


class InMemoryMarketplaceCatalogStore:
    """Test adapter for the marketplace catalog workspace interface."""

    def __init__(self) -> None:
        self.snapshots: dict[tuple[str, str], dict[str, Any]] = {}

    def save_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        key = (snapshot["store_ref"], snapshot["idempotency_key"])
        existing = self.snapshots.get(key)
        if existing is not None:
            if existing["snapshot_hash"] != snapshot["snapshot_hash"]:
                raise ValueError(
                    "Marketplace catalog idempotency conflict; "
                    "changed Evidence requires a new idempotency key"
                )
            return deepcopy(existing)
        self.snapshots[key] = deepcopy(snapshot)
        return deepcopy(snapshot)

    def latest_items(self, *, store_ref: str, limit: int) -> list[dict[str, Any]]:
        candidates = [
            {**deepcopy(item), "snapshot_id": snapshot["id"]}
            for snapshot in self.snapshots.values()
            if snapshot["store_ref"] == store_ref
            for item in snapshot["items"]
        ]
        candidates.sort(
            key=lambda item: (
                item["offer_id"],
                item["observed_at"],
                item["snapshot_id"],
            ),
            reverse=True,
        )
        latest: dict[str, dict[str, Any]] = {}
        for item in candidates:
            latest.setdefault(item["offer_id"], item)
        return sorted(
            latest.values(),
            key=lambda item: (item["observed_at"], item["offer_id"]),
            reverse=True,
        )[:limit]


class SqlMarketplaceCatalogStore:
    """PostgreSQL adapter; callers do not need to know the persistence shape."""

    def __init__(self, engine) -> None:
        self.engine = engine

    def save_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        with self.engine.begin() as connection:
            inserted = connection.execute(
                text(
                    """
                    INSERT INTO marketplace_catalog_snapshots (
                        id, marketplace, store_ref, idempotency_key, snapshot_hash,
                        contract_version, evidence_ids_json, imported_by, imported_at,
                        observed_at, item_count
                    ) VALUES (
                        :id, :marketplace, :store_ref, :idempotency_key,
                        :snapshot_hash, :contract_version,
                        CAST(:evidence_ids_json AS jsonb), :imported_by, :imported_at,
                        :observed_at, :item_count
                    )
                    ON CONFLICT (store_ref, idempotency_key) DO NOTHING
                    RETURNING id
                    """
                ),
                {
                    **{
                        key: snapshot[key]
                        for key in (
                            "id",
                            "marketplace",
                            "store_ref",
                            "idempotency_key",
                            "snapshot_hash",
                            "contract_version",
                            "imported_by",
                            "imported_at",
                            "observed_at",
                            "item_count",
                        )
                    },
                    "evidence_ids_json": json.dumps(snapshot["evidence_ids"]),
                },
            ).scalar_one_or_none()
            if inserted is None:
                existing = (
                    connection.execute(
                        text(
                            """
                            SELECT id, snapshot_hash
                            FROM marketplace_catalog_snapshots
                            WHERE store_ref = :store_ref
                              AND idempotency_key = :idempotency_key
                            """
                        ),
                        {
                            "store_ref": snapshot["store_ref"],
                            "idempotency_key": snapshot["idempotency_key"],
                        },
                    )
                    .mappings()
                    .one()
                )
                if existing["snapshot_hash"] != snapshot["snapshot_hash"]:
                    raise ValueError(
                        "Marketplace catalog idempotency conflict; "
                        "changed Evidence requires a new idempotency key"
                    )
                return self._snapshot(connection, existing["id"])
            connection.execute(
                text(
                    """
                    INSERT INTO marketplace_catalog_items (
                        snapshot_id, offer_id, marketplace_sku, name, currency_code,
                        prices_json, available_stock, stocks_json, statuses_json,
                        dimensions_json, attributes_json,
                        attributes_with_defaults_json, complex_attributes_json,
                        image_references_json, video_references_json,
                        document_references_json, media_rights_status,
                        source_evidence_id, observed_at, item_hash,
                        canonical_product_id
                    ) VALUES (
                        :snapshot_id, :offer_id, :marketplace_sku, :name,
                        :currency_code, CAST(:prices_json AS jsonb), :available_stock,
                        CAST(:stocks_json AS jsonb), CAST(:statuses_json AS jsonb),
                        CAST(:dimensions_json AS jsonb), CAST(:attributes_json AS jsonb),
                        CAST(:attributes_with_defaults_json AS jsonb),
                        CAST(:complex_attributes_json AS jsonb),
                        CAST(:image_references_json AS jsonb),
                        CAST(:video_references_json AS jsonb),
                        CAST(:document_references_json AS jsonb), :media_rights_status,
                        :source_evidence_id, :observed_at, :item_hash,
                        :canonical_product_id
                    )
                    """
                ),
                [
                    {
                        **item,
                        "snapshot_id": snapshot["id"],
                        **{
                            f"{field}_json": json.dumps(item[field])
                            for field in (
                                "prices",
                                "stocks",
                                "statuses",
                                "dimensions",
                                "attributes",
                                "attributes_with_defaults",
                                "complex_attributes",
                                "image_references",
                                "video_references",
                                "document_references",
                            )
                        },
                    }
                    for item in snapshot["items"]
                ],
            )
            return deepcopy(snapshot)

    def latest_items(self, *, store_ref: str, limit: int) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT *
                        FROM (
                            SELECT item.*,
                                   row_number() OVER (
                                       PARTITION BY item.offer_id
                                       ORDER BY item.observed_at DESC,
                                                snapshot.imported_at DESC,
                                                snapshot.id DESC
                                   ) AS latest_rank
                            FROM marketplace_catalog_items AS item
                            JOIN marketplace_catalog_snapshots AS snapshot
                              ON snapshot.id = item.snapshot_id
                            WHERE snapshot.store_ref = :store_ref
                        ) AS ranked
                        WHERE latest_rank = 1
                        ORDER BY observed_at DESC, offer_id
                        LIMIT :limit
                        """
                    ),
                    {"store_ref": store_ref, "limit": limit},
                )
                .mappings()
                .all()
            )
        return [self._item(row) for row in rows]

    def _snapshot(self, connection, snapshot_id: str) -> dict[str, Any]:
        snapshot = (
            connection.execute(
                text(
                    "SELECT * FROM marketplace_catalog_snapshots WHERE id = :id"
                ),
                {"id": snapshot_id},
            )
            .mappings()
            .one()
        )
        items = (
            connection.execute(
                text(
                    """
                    SELECT * FROM marketplace_catalog_items
                    WHERE snapshot_id = :id ORDER BY offer_id
                    """
                ),
                {"id": snapshot_id},
            )
            .mappings()
            .all()
        )
        return {
            "id": snapshot["id"],
            "marketplace": snapshot["marketplace"],
            "store_ref": snapshot["store_ref"],
            "idempotency_key": snapshot["idempotency_key"],
            "snapshot_hash": snapshot["snapshot_hash"],
            "contract_version": snapshot["contract_version"],
            "evidence_ids": list(snapshot["evidence_ids_json"]),
            "imported_by": snapshot["imported_by"],
            "imported_at": snapshot["imported_at"].isoformat(),
            "observed_at": snapshot["observed_at"].isoformat(),
            "item_count": snapshot["item_count"],
            "items": [self._item(row) for row in items],
        }

    @staticmethod
    def _item(row) -> dict[str, Any]:
        return {
            "offer_id": row["offer_id"],
            "marketplace_sku": row["marketplace_sku"],
            "name": row["name"],
            "currency_code": row["currency_code"],
            "prices": row["prices_json"],
            "available_stock": row["available_stock"],
            "stocks": row["stocks_json"],
            "statuses": row["statuses_json"],
            "dimensions": row["dimensions_json"],
            "attributes": row["attributes_json"],
            "attributes_with_defaults": row["attributes_with_defaults_json"],
            "complex_attributes": row["complex_attributes_json"],
            "image_references": row["image_references_json"],
            "video_references": row["video_references_json"],
            "document_references": row["document_references_json"],
            "media_rights_status": row["media_rights_status"],
            "source_evidence_id": row["source_evidence_id"],
            "observed_at": row["observed_at"].isoformat(),
            "item_hash": row["item_hash"],
            "canonical_product_id": row["canonical_product_id"],
            "snapshot_id": row["snapshot_id"],
        }


class MarketplaceCatalogWorkspace:
    """Turn verified platform response Evidence into immutable catalog read models."""

    def __init__(
        self,
        *,
        verified_bundle_loader: Callable[[str], tuple[bytes, Any]],
        store,
        evidence,
    ) -> None:
        self.verified_bundle_loader = verified_bundle_loader
        self.store = store
        self.evidence = evidence

    def import_ozon_evidence(
        self,
        *,
        evidence_ids: list[str],
        store_ref: str,
        idempotency_key: str,
        imported_by: str,
    ) -> dict[str, Any]:
        normalized_ids = sorted(
            {item.strip() for item in evidence_ids if item.strip()}
        )
        if not normalized_ids or len(normalized_ids) != len(evidence_ids):
            raise ValueError(
                "Marketplace catalog requires unique non-empty Evidence references"
            )
        if len(normalized_ids) > 50:
            raise ValueError("Marketplace catalog import is limited to 50 Evidence records")
        store_scope = _required_text(store_ref, "store_ref", max_length=160)
        key = _required_text(
            idempotency_key, "idempotency_key", max_length=160
        )
        actor = _required_text(imported_by, "imported_by", max_length=160)

        items: list[dict[str, Any]] = []
        evidence_times: list[datetime] = []
        for evidence_id in normalized_ids:
            content, record = self.verified_bundle_loader(evidence_id)
            observed = datetime.fromisoformat(
                record.effective_at.replace("Z", "+00:00")
            )
            if observed.tzinfo is None:
                raise ValueError("Ozon Evidence effective time must include a timezone")
            observed = observed.astimezone(UTC)
            evidence_times.append(observed)
            items.append(
                parse_ozon_product_bundle(
                    content,
                    source_evidence_id=evidence_id,
                    observed_at=observed.isoformat(),
                )
            )
        offer_ids = [item["offer_id"] for item in items]
        if len(offer_ids) != len(set(offer_ids)):
            raise ValueError("Marketplace catalog import contains duplicate offer IDs")
        items.sort(key=lambda item: item["offer_id"])
        imported_at = datetime.now(UTC).isoformat()
        observed_at = max(evidence_times).isoformat()
        snapshot_hash = _canonical_hash(
            {
                "marketplace": "ozon",
                "store_ref": store_scope,
                "contract_version": OZON_PRODUCT_CONTRACT_VERSION,
                "evidence_ids": normalized_ids,
                "items": items,
            }
        )
        snapshot = {
            "id": new_id("mcs"),
            "marketplace": "ozon",
            "store_ref": store_scope,
            "idempotency_key": key,
            "snapshot_hash": snapshot_hash,
            "contract_version": OZON_PRODUCT_CONTRACT_VERSION,
            "evidence_ids": normalized_ids,
            "imported_by": actor,
            "imported_at": imported_at,
            "observed_at": observed_at,
            "item_count": len(items),
            "items": items,
        }
        saved = self.store.save_snapshot(snapshot)
        for evidence_id in normalized_ids:
            self.evidence.link(
                evidence_id=evidence_id,
                target_type="marketplace_catalog_snapshot",
                target_id=saved["id"],
                relationship="catalog_source",
                created_by=actor,
            )
        return saved

    def latest_items(
        self, *, store_ref: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        store_scope = _required_text(store_ref, "store_ref", max_length=160)
        if limit < 1 or limit > 1000:
            raise ValueError("Marketplace catalog item limit must be 1 to 1000")
        return self.store.latest_items(store_ref=store_scope, limit=limit)

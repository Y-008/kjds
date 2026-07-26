from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from .domain import Product, ProductStatus, new_id

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
        self.bindings: dict[tuple[str, str, str], dict[str, Any]] = {}

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
        projected = []
        for item in latest.values():
            binding = self.bindings.get(("ozon", store_ref, item["offer_id"]))
            projected.append(
                {
                    **item,
                    "canonical_product_id": (
                        binding["product_id"]
                        if binding is not None
                        else item["canonical_product_id"]
                    ),
                }
            )
        return sorted(
            projected,
            key=lambda item: (item["observed_at"], item["offer_id"]),
            reverse=True,
        )[:limit]

    def get_binding(
        self, *, marketplace: str, store_ref: str, offer_id: str
    ) -> dict[str, Any] | None:
        binding = self.bindings.get((marketplace, store_ref, offer_id))
        return deepcopy(binding) if binding is not None else None

    def save_binding(self, binding: dict[str, Any]) -> dict[str, Any]:
        key = (
            binding["marketplace"],
            binding["store_ref"],
            binding["offer_id"],
        )
        existing = self.bindings.get(key)
        if existing is not None:
            self._require_same_binding(existing, binding)
            return deepcopy(existing)
        product_owner = next(
            (
                item
                for item in self.bindings.values()
                if item["product_id"] == binding["product_id"]
            ),
            None,
        )
        if product_owner is not None:
            raise ValueError("Canonical product already belongs to another marketplace listing")
        self.bindings[key] = deepcopy(binding)
        return deepcopy(binding)

    @staticmethod
    def _require_same_binding(
        existing: dict[str, Any], proposed: dict[str, Any]
    ) -> None:
        # The identity is immutable, while the original Evidence/hash remain frozen on
        # the stored binding. A later catalog snapshot may legitimately carry fresher
        # provenance for the same listing and must not rewrite the original basis.
        immutable_fields = {
            "marketplace",
            "store_ref",
            "offer_id",
            "product_id",
        }
        if any(existing.get(key) != proposed.get(key) for key in immutable_fields):
            raise ValueError("Marketplace listing is already bound to different immutable terms")


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
                                   binding.product_id AS bound_product_id,
                                   row_number() OVER (
                                       PARTITION BY item.offer_id
                                       ORDER BY item.observed_at DESC,
                                                snapshot.imported_at DESC,
                                                snapshot.id DESC
                                   ) AS latest_rank
                            FROM marketplace_catalog_items AS item
                            JOIN marketplace_catalog_snapshots AS snapshot
                              ON snapshot.id = item.snapshot_id
                            LEFT JOIN marketplace_product_bindings AS binding
                              ON binding.marketplace = snapshot.marketplace
                             AND binding.store_ref = snapshot.store_ref
                             AND binding.offer_id = item.offer_id
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

    def get_binding(
        self, *, marketplace: str, store_ref: str, offer_id: str
    ) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT *
                        FROM marketplace_product_bindings
                        WHERE marketplace = :marketplace
                          AND store_ref = :store_ref
                          AND offer_id = :offer_id
                        """
                    ),
                    {
                        "marketplace": marketplace,
                        "store_ref": store_ref,
                        "offer_id": offer_id,
                    },
                )
                .mappings()
                .first()
            )
        return self._binding(row) if row is not None else None

    def save_binding(self, binding: dict[str, Any]) -> dict[str, Any]:
        try:
            with self.engine.begin() as connection:
                inserted = connection.execute(
                    text(
                        """
                        INSERT INTO marketplace_product_bindings (
                            marketplace, store_ref, offer_id, marketplace_sku,
                            product_id, source_evidence_id, item_hash, bound_by, bound_at
                        ) VALUES (
                            :marketplace, :store_ref, :offer_id, :marketplace_sku,
                            :product_id, :source_evidence_id, :item_hash, :bound_by, :bound_at
                        )
                        ON CONFLICT (marketplace, store_ref, offer_id) DO NOTHING
                        RETURNING marketplace
                        """
                    ),
                    binding,
                ).scalar_one_or_none()
                if inserted is not None:
                    return dict(binding)
                row = (
                    connection.execute(
                        text(
                            """
                            SELECT *
                            FROM marketplace_product_bindings
                            WHERE marketplace = :marketplace
                              AND store_ref = :store_ref
                              AND offer_id = :offer_id
                            """
                        ),
                        binding,
                    )
                    .mappings()
                    .one()
                )
                existing = self._binding(row)
                InMemoryMarketplaceCatalogStore._require_same_binding(
                    existing, binding
                )
                return existing
        except IntegrityError as exc:
            raise ValueError(
                "Canonical product already belongs to another marketplace listing"
            ) from exc

    @staticmethod
    def _binding(row) -> dict[str, Any]:
        return {
            "marketplace": row["marketplace"],
            "store_ref": row["store_ref"],
            "offer_id": row["offer_id"],
            "marketplace_sku": row["marketplace_sku"],
            "product_id": row["product_id"],
            "source_evidence_id": row["source_evidence_id"],
            "item_hash": row["item_hash"],
            "bound_by": row["bound_by"],
            "bound_at": (
                row["bound_at"].isoformat()
                if hasattr(row["bound_at"], "isoformat")
                else str(row["bound_at"])
            ),
        }

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
            "canonical_product_id": (
                row.get("bound_product_id") or row["canonical_product_id"]
            ),
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
        repository,
    ) -> None:
        self.verified_bundle_loader = verified_bundle_loader
        self.store = store
        self.evidence = evidence
        self.repository = repository

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

    def require_bound_current_item(
        self,
        *,
        store_ref: str,
        offer_id: str,
        expected_item_hash: str,
    ) -> dict[str, Any]:
        store_scope, external_offer_id, item = self._require_current_item(
            store_ref=store_ref,
            offer_id=offer_id,
            expected_item_hash=expected_item_hash,
        )
        binding = self.store.get_binding(
            marketplace="ozon",
            store_ref=store_scope,
            offer_id=external_offer_id,
        )
        if binding is None:
            raise ValueError("Marketplace listing must be bound before downstream work")
        product = self.repository.get_product(binding["product_id"])
        if (
            product.status != ProductStatus.ACTIVE
            or product.channel != "OZON"
            or product.market != "RU"
        ):
            raise ValueError("Bound marketplace product is not active for Ozon RU")
        return {
            "item": item,
            "binding": binding,
            "product": product,
        }

    def bind_existing_listing(
        self,
        *,
        store_ref: str,
        offer_id: str,
        expected_item_hash: str,
        confirmed: bool,
        bound_by: str,
    ) -> dict[str, Any]:
        if not confirmed:
            raise ValueError("Existing listing binding requires explicit human confirmation")
        actor = _required_text(bound_by, "bound_by", max_length=160)
        store_scope, external_offer_id, item = self._require_current_item(
            store_ref=store_ref,
            offer_id=offer_id,
            expected_item_hash=expected_item_hash,
        )

        identity = json.dumps(
            {
                "marketplace": "ozon",
                "store_ref": store_scope,
                "offer_id": external_offer_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        product_id = f"prd_{hashlib.sha256(identity).hexdigest()[:32]}"
        canonical_sku = f"ozon:{store_scope}:{external_offer_id}"
        binding = {
            "marketplace": "ozon",
            "store_ref": store_scope,
            "offer_id": external_offer_id,
            "marketplace_sku": item["marketplace_sku"],
            "product_id": product_id,
            "source_evidence_id": item["source_evidence_id"],
            "item_hash": item["item_hash"],
            "bound_by": actor,
            "bound_at": datetime.now(UTC).isoformat(),
        }

        existing_binding = self.store.get_binding(
            marketplace="ozon",
            store_ref=store_scope,
            offer_id=external_offer_id,
        )
        if (
            existing_binding is not None
            and existing_binding["product_id"] != product_id
        ):
            raise ValueError(
                "Marketplace listing is already bound to a different canonical product"
            )
        products = self.repository.list_products()
        product_by_id = next(
            (product for product in products if product.id == product_id),
            None,
        )
        product_by_sku = next(
            (
                product
                for product in products
                if product.sku == canonical_sku
            ),
            None,
        )
        if (
            product_by_id is not None
            and product_by_id.sku != canonical_sku
        ) or (
            product_by_sku is not None
            and product_by_sku.id != product_id
        ):
            raise ValueError(
                "Marketplace offer ID already belongs to a different canonical product"
            )
        existing_product = product_by_id or product_by_sku
        if existing_product is not None and (
            existing_product.market != "RU"
            or existing_product.channel != "OZON"
        ):
            raise ValueError(
                "Marketplace offer ID already belongs to a different canonical product"
            )

        created = False
        product = existing_product
        if product is None:
            product = Product(
                id=product_id,
                sku=canonical_sku,
                name=item["name"],
                market="RU",
                channel="OZON",
                status=ProductStatus.PAUSED,
            )
            try:
                with self.repository.transaction():
                    self.repository.add_product(product)
                    self.repository.append_event(
                        "product.created",
                        product.id,
                        {
                            "sku": product.sku,
                            "origin": "existing_ozon_listing",
                        },
                        actor_id=actor,
                        source_evidence_id=item["source_evidence_id"],
                    )
                created = True
            except ValueError:
                product = next(
                    (
                        candidate
                        for candidate in self.repository.list_products()
                        if candidate.sku == canonical_sku
                    ),
                    None,
                )
                if product is None or product.id != product_id:
                    raise

        saved_binding = (
            existing_binding
            if existing_binding is not None
            else self.store.save_binding(binding)
        )
        InMemoryMarketplaceCatalogStore._require_same_binding(
            saved_binding, binding
        )
        if product.status != ProductStatus.ACTIVE:
            product.status = ProductStatus.ACTIVE
            self.repository.save_product(product)
        handoff_recorded = any(
            event["type"]
            == "product.existing_listing_growth_workspace_created"
            and event["aggregate_id"] == product.id
            for event in self.repository.events_after(0)
        )
        if not handoff_recorded:
            self.repository.append_event(
                "product.existing_listing_growth_workspace_created",
                product.id,
                {
                    "marketplace": "ozon",
                    "store_ref": store_scope,
                    "offer_id": external_offer_id,
                    "marketplace_sku": item["marketplace_sku"],
                    "item_hash": item["item_hash"],
                    "bound_by": actor,
                },
                actor_id=actor,
                source_evidence_id=item["source_evidence_id"],
            )
        self.evidence.link(
            evidence_id=item["source_evidence_id"],
            target_type="product",
            target_id=product.id,
            relationship="existing_listing_basis",
            created_by=actor,
        )
        return {
            "product": product,
            "binding": saved_binding,
            "created": created,
            "next_gate": "supplier_quote_authority",
            "counts_as_new_candidate": False,
            "media_rights_status": item["media_rights_status"],
            "automatic_procurement": False,
            "automatic_listing": False,
            "automatic_marketplace_write": False,
        }

    def _require_current_item(
        self,
        *,
        store_ref: str,
        offer_id: str,
        expected_item_hash: str,
    ) -> tuple[str, str, dict[str, Any]]:
        store_scope = _required_text(store_ref, "store_ref", max_length=160)
        external_offer_id = _required_text(
            offer_id, "offer_id", max_length=160
        )
        expected_hash = _required_text(
            expected_item_hash, "expected_item_hash", max_length=64
        )
        if len(expected_hash) != 64 or any(
            character not in "0123456789abcdef" for character in expected_hash
        ):
            raise ValueError("Expected catalog item hash must be lowercase SHA-256")
        item = next(
            (
                candidate
                for candidate in self.store.latest_items(
                    store_ref=store_scope,
                    limit=1000,
                )
                if candidate["offer_id"] == external_offer_id
            ),
            None,
        )
        if item is None:
            raise KeyError("Unknown current marketplace catalog item")
        if item["item_hash"] != expected_hash:
            raise ValueError("Catalog item changed; refresh before continuing")
        self.evidence.require_current([item["source_evidence_id"]])
        return store_scope, external_offer_id, item

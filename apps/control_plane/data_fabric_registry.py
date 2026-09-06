"""Read-only loader for the versioned KJDS data-product registry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .data_fabric_contracts import DataProductDescriptor

DEFAULT_REGISTRY_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "project"
    / "registries"
    / "data_products.json"
)


class DataProductRegistryError(ValueError):
    """Raised when a registry is malformed or contains duplicate products."""


def load_data_product_registry(
    path: str | Path = DEFAULT_REGISTRY_PATH,
) -> tuple[DataProductDescriptor, ...]:
    registry_path = Path(path)
    try:
        payload: Any = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataProductRegistryError(
            f"unable to read data-product registry: {registry_path}"
        ) from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("products"), list):
        raise DataProductRegistryError("registry must contain a products list")

    products: list[DataProductDescriptor] = []
    seen: set[str] = set()
    for raw_product in payload["products"]:
        if not isinstance(raw_product, dict):
            raise DataProductRegistryError("registry product must be an object")
        product_id = raw_product.get("id")
        if not isinstance(product_id, str) or not product_id:
            raise DataProductRegistryError("registry product id is required")
        if product_id in seen:
            raise DataProductRegistryError(f"duplicate registry product: {product_id}")
        seen.add(product_id)
        try:
            products.append(
                DataProductDescriptor(
                    dataset_id=product_id,
                    version=raw_product.get("version", "1"),
                    owner=raw_product.get("owner", "unassigned"),
                    grain=raw_product["grain"],
                    source_refs=tuple(raw_product.get("source_refs", ())),
                    allowed_scopes=tuple(raw_product.get("allowed_scopes", ())),
                    allowed_purposes=tuple(raw_product.get("allowed_purposes", ())),
                    refresh_sla_seconds=raw_product.get("refresh_sla_seconds"),
                    quality_threshold=raw_product.get("quality_threshold", 0),
                    rebuild_method=raw_product.get("rebuild_method", "registered source replay"),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise DataProductRegistryError(
                f"invalid registry product: {product_id}"
            ) from exc
    return tuple(products)


def get_data_product(
    dataset_id: str,
    *,
    path: str | Path = DEFAULT_REGISTRY_PATH,
) -> DataProductDescriptor | None:
    return next(
        (product for product in load_data_product_registry(path) if product.dataset_id == dataset_id),
        None,
    )

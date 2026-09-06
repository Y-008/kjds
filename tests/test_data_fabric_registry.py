import json

import pytest

from apps.control_plane.data_fabric_registry import (
    DataProductRegistryError,
    get_data_product,
    load_data_product_registry,
)


def test_load_repository_registry_and_find_product() -> None:
    products = load_data_product_registry()

    assert products
    assert get_data_product("profit.cm3.v1") is not None
    assert get_data_product("missing.v1") is None
    product = get_data_product("profit.cm3.v1")
    assert product is not None
    assert product.status == "contract_only"
    assert product.authority == "projection"


def test_registry_rejects_duplicate_ids(tmp_path) -> None:
    path = tmp_path / "data_products.json"
    path.write_text(
        json.dumps(
            {
                "products": [
                    {"id": "dup", "grain": "row"},
                    {"id": "dup", "grain": "row"},
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(DataProductRegistryError, match="duplicate"):
        load_data_product_registry(path)


def test_registry_rejects_invalid_payload(tmp_path) -> None:
    path = tmp_path / "data_products.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(DataProductRegistryError, match="products list"):
        load_data_product_registry(path)


def test_registry_rejects_invalid_status(tmp_path) -> None:
    path = tmp_path / "data_products.json"
    path.write_text(json.dumps({"status": "live", "products": []}), encoding="utf-8")
    with pytest.raises(DataProductRegistryError, match="status"):
        load_data_product_registry(path)

from __future__ import annotations

import pytest

from apps.control_plane.ai_listing import AiListingPipeline, AiListingPipelineError


def _pipeline() -> AiListingPipeline:
    return object.__new__(AiListingPipeline)


def _contract() -> dict:
    return {
        "type_id": 97946,
        "description_category_id": 17028634,
        "attributes": {
            "85": {"id": 85, "name": "Бренд", "is_required": True},
            "8229": {"id": 8229, "name": "Тип", "is_required": True},
            "9048": {"id": 9048, "name": "Название модели", "is_required": True},
            "10096": {"id": 10096, "name": "Цвет товара", "is_required": False},
        },
    }


def test_required_only_contract_keeps_only_required_attributes() -> None:
    contract = _contract()
    slim = AiListingPipeline._required_only_contract(contract)
    assert set(slim["attributes"]) == {"85", "8229", "9048"}
    assert slim["type_id"] == contract["type_id"]


def test_required_only_contract_passthrough_non_dict() -> None:
    assert AiListingPipeline._required_only_contract(None) is None
    assert AiListingPipeline._required_only_contract({"type_id": 1}) == {"type_id": 1}
    assert AiListingPipeline._required_only_contract({"attributes": [{"id": 1}]}) == {
        "attributes": [{"id": 1}]
    }


def _result(missing: list) -> dict:
    return {
        "candidates": [
            {"category_id": "97946", "reason": "match", "confidence": 0.95}
        ],
        "attribute_mapping": {"85": "Нет бренда", "8229": "Органайзер", "9048": "xk005"},
        "missing_required_attributes": missing,
    }


def test_validate_taxonomy_treats_blank_missing_as_filled() -> None:
    # Local models sometimes emit [""] instead of []; that is not a missing
    # required attribute and must not block the governed gate.
    _pipeline()._validate_taxonomy(
        _result([""]),
        candidates=[{"category_id": "97946"}, {"category_id": "91548"}],
        attributes=_contract(),
    )


def test_validate_taxonomy_still_rejects_real_missing_attribute() -> None:
    with pytest.raises(AiListingPipelineError) as exc:
        _pipeline()._validate_taxonomy(
            _result(["85"]),
            candidates=[{"category_id": "97946"}, {"category_id": "91548"}],
            attributes=_contract(),
        )
    assert exc.value.code == "required_ozon_attributes_missing"

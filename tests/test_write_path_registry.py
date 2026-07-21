import json
from pathlib import Path

import pytest

from apps.control_plane.write_paths import (
    WritePathRegistry,
    WritePathRegistryError,
    validate_repository_write_paths,
)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "docs" / "project" / "registries" / "write_path_registry.json"


def test_write_path_registry_covers_policy_and_source_boundaries():
    registry = WritePathRegistry(REGISTRY)

    assert registry.get("candidate_promote")["availability"] == "enabled"
    assert registry.get("listing_publish")["single_use_permit"] is True
    assert registry.get("sample_pay")["availability"] == "policy_only"
    validate_repository_write_paths(ROOT)


def test_write_path_registry_fails_when_an_action_is_missing(tmp_path):
    value = json.loads(REGISTRY.read_text(encoding="utf-8"))
    value["actions"] = [
        item for item in value["actions"] if item["action_id"] != "listing_publish"
    ]
    path = tmp_path / "write-paths.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(WritePathRegistryError, match="exactly cover"):
        WritePathRegistry(path)


def test_write_path_registry_fails_when_high_risk_permit_is_not_single_use(tmp_path):
    value = json.loads(REGISTRY.read_text(encoding="utf-8"))
    listing_publish = next(
        item for item in value["actions"] if item["action_id"] == "listing_publish"
    )
    listing_publish["single_use_permit"] = False
    path = tmp_path / "write-paths.json"
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(WritePathRegistryError, match="single-use permit"):
        WritePathRegistry(path)

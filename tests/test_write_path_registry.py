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
    assert registry.get("customer_service_reply_send")["availability"] == "policy_only"
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


def test_repository_validation_fails_when_delivery_class_drifts(tmp_path):
    root = _copy_validation_sources(tmp_path)
    registry = _registry_value()
    _listing_publish(registry)["delivery"]["entry"] = (
        "apps.control_plane.ozon_worker.MissingExecutionWorker"
    )
    _write_registry(root, registry)

    with pytest.raises(WritePathRegistryError, match="delivery dotted entry"):
        validate_repository_write_paths(root)


def test_repository_validation_fails_when_worker_action_or_adapter_drifts(tmp_path):
    root = _copy_validation_sources(tmp_path)
    worker = root / "apps" / "control_plane" / "ozon_worker.py"
    source = worker.read_text(encoding="utf-8")
    worker.write_text(
        source.replace('ADAPTER_ID = "ozon.product.import.v3"', 'ADAPTER_ID = "missing.adapter"'),
        encoding="utf-8",
    )

    with pytest.raises(WritePathRegistryError, match="Worker adapter drifted"):
        validate_repository_write_paths(root)

    worker.write_text(
        source.replace('ACTION_ID = "listing_publish"', 'ACTION_ID = "listing_draft"'),
        encoding="utf-8",
    )
    with pytest.raises(WritePathRegistryError, match="Worker action drifted"):
        validate_repository_write_paths(root)


def test_repository_validation_fails_when_external_endpoint_drifts(tmp_path):
    root = _copy_validation_sources(tmp_path)
    registry = _registry_value()
    _listing_publish(registry)["external_calls"][0] = (
        "POST Ozon /v9/product/info/list [before-read]"
    )
    _write_registry(root, registry)

    with pytest.raises(WritePathRegistryError, match="External endpoint drifted"):
        validate_repository_write_paths(root)


def test_listing_publish_registry_covers_the_governed_execution_path():
    assert set(_listing_publish(_registry_value())["request_entries"]) == {
        "POST /v1/listings/ozon/drafts/{draft_id}/execution-plan",
        "POST /v1/causal-policy-activation-handoffs/{handoff_id}/execution-plans",
        "POST /v1/governed-execution-plans/{plan_id}/dry-run",
        "POST /v1/governed-execution-plans/{plan_id}/commands",
        "POST /v1/limited-execution-commands/{command_id}/claim",
        "POST /v1/limited-execution-commands/{command_id}/write-attempt",
        "POST /v1/limited-execution-commands/{command_id}/response-checkpoint",
        "POST /v1/limited-execution-commands/{command_id}/receipt",
        "POST /v1/limited-execution-commands/{command_id}/rollback",
    }


def test_repository_validation_fails_when_request_route_drifts(tmp_path):
    root = _copy_validation_sources(tmp_path)
    registry = _registry_value()
    _listing_publish(registry)["request_entries"][0] = (
        "POST /v1/listings/ozon/drafts/{draft_id}/publish-now"
    )
    _write_registry(root, registry)

    with pytest.raises(WritePathRegistryError, match="Request entry drifted"):
        validate_repository_write_paths(root)


def _copy_validation_sources(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for relative in (
        Path("apps/control_plane/action_policies.py"),
        Path("apps/control_plane/ai_listing.py"),
        Path("apps/control_plane/channel_account_governance.py"),
        Path("apps/control_plane/execution_plans.py"),
        Path("apps/control_plane/image_execution.py"),
        Path("apps/control_plane/intelligence.py"),
        Path("apps/control_plane/limited_executor.py"),
        Path("apps/control_plane/marketplace_research_mcp.py"),
        Path("apps/control_plane/ozon_read_worker.py"),
        Path("apps/control_plane/ozon_worker.py"),
        Path("apps/control_plane/providers.py"),
        Path("apps/control_plane/profit_erp_sync.py"),
        Path("apps/control_plane/repository.py"),
        Path("apps/control_plane/routers/execution_operations.py"),
        Path("apps/control_plane/routers/ai_listing.py"),
        Path("apps/control_plane/routers/channel_accounts.py"),
        Path("apps/control_plane/routers/ozon_platform.py"),
        Path("apps/control_plane/routers/product_content.py"),
        Path("apps/control_plane/routers/erp_integration.py"),
        Path("apps/control_plane/sourcing.py"),
        Path("apps/control_plane/sourcing_store.py"),
        Path("docs/project/registries/action_policy_registry.json"),
        Path("docs/project/registries/write_path_registry.json"),
    ):
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text((ROOT / relative).read_text(encoding="utf-8"), encoding="utf-8")
    return root


def _registry_value() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def _listing_publish(value: dict) -> dict:
    return next(item for item in value["actions"] if item["action_id"] == "listing_publish")


def _write_registry(root: Path, value: dict) -> None:
    path = root / "docs" / "project" / "registries" / "write_path_registry.json"
    path.write_text(json.dumps(value), encoding="utf-8")

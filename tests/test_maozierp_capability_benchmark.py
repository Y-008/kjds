import hashlib
import json
from collections import Counter
from pathlib import Path

REGISTRY_PATH = (
    Path(__file__).parents[1]
    / "docs"
    / "project"
    / "registries"
    / "maozierp_feishu_capability_benchmark.json"
)


def _canonical_hash(registry: dict) -> str:
    unsigned = json.loads(json.dumps(registry))
    unsigned["source"].pop("capability_snapshot_sha256")
    payload = json.dumps(
        unsigned,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def test_maozierp_public_document_capabilities_are_all_mapped_without_completion_claim():
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    capabilities = registry["capabilities"]
    ids = {item["id"] for item in capabilities}

    assert registry["source"]["url"] == (
        "https://mcn5ze6lo0iz.feishu.cn/wiki/"
        "Zd2xwn5m4ijIaQkiDc7c34qgnye"
    )
    assert registry["source"]["evidence_tier"] == "C"
    assert registry["source"]["authority"] == (
        "workflow_and_capability_observation_only"
    )
    assert len(capabilities) == len(ids) == 28
    assert registry["coverage"]["observed_capability_count"] == len(capabilities)
    assert registry["coverage"]["mapped_count"] == len(capabilities)
    assert registry["coverage"]["unmapped_count"] == 0
    assert registry["coverage"]["implementation_is_not_claimed_by_mapping"] is True
    assert registry["coverage"]["external_write_allowed"] is False

    expected_counts = Counter(item["adoption"] for item in capabilities)
    assert registry["coverage"]["adoption_summary"] == dict(expected_counts)
    assert all(item["kjds_target"] for item in capabilities)
    assert all(item["wave"] for item in capabilities)
    assert all(item["status"] for item in capabilities)
    assert all(item["boundary"] for item in capabilities)


def test_maozierp_snapshot_hash_and_high_risk_workflows_are_fail_closed():
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    by_id = {item["id"]: item for item in registry["capabilities"]}

    assert registry["source"]["capability_snapshot_sha256"] == _canonical_hash(
        registry
    )
    assert by_id["cookie_binding"]["adoption"] == "reject"
    assert "never transfer cookies" in by_id["cookie_binding"]["boundary"]
    assert by_id["multi_store_cookie_session"]["adoption"] == "replace"
    assert "no shared cookies" in by_id["multi_store_cookie_session"]["boundary"]
    assert by_id["image_collection"]["status"] == "gated"
    assert "rights Evidence" in by_id["image_collection"]["boundary"]
    assert by_id["one_click_multi_store_listing"]["status"] == "gated"
    assert "one-time Permit" in by_id["one_click_multi_store_listing"]["boundary"]
    assert by_id["auto_favorite_bulk_listing"]["adoption"] == "replace"
    assert "separately approved external command" in (
        by_id["auto_favorite_bulk_listing"]["boundary"]
    )

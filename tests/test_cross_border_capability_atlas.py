import json

import pytest

from apps.control_plane.cross_border_capability_atlas import (
    CapabilityAtlasError,
    CrossBorderCapabilityAtlas,
)
from apps.control_plane.runtime import runtime


def test_atlas_exposes_complete_russia_first_tree_with_truthful_boundaries():
    snapshot = runtime.cross_border_capability_atlas.snapshot()

    assert snapshot["contract_id"] == "kjds-cross-border-capability-atlas-v1"
    assert snapshot["release_version"] == "0.56.0"
    assert snapshot["registry_version"] == "0.56.0"
    assert snapshot["primary_market"] == "RU"
    assert snapshot["primary_platform"] == "ozon"
    assert snapshot["counts"]["domains"] == 10
    assert snapshot["counts"]["capabilities"] >= 45
    assert snapshot["counts"]["atomic_points"] >= 140
    assert snapshot["counts"]["value_streams"] == 14
    assert snapshot["counts"]["operating_surfaces"] == 8
    assert sum(snapshot["counts"]["statuses"].values()) == snapshot["counts"]["capabilities"]
    assert (
        sum(snapshot["counts"]["atomic_point_statuses"].values())
        == snapshot["counts"]["atomic_points"]
    )
    assert snapshot["counts"]["linkfox_reference"]["observed"] > 0
    assert snapshot["counts"]["linkfox_reference"]["not_observed"] > 0
    assert len(snapshot["registry_sha256"]) == 64
    assert snapshot["control_envelope"] == {
        "read_only": True,
        "marketing_claims_are_business_facts": False,
        "linkfox_ozon_integration_verified": False,
        "client_can_promote_status": False,
        "external_write_allowed": False,
        "operating_graph_is_execution_authority": False,
        "expansion_rule": (
            "official contract, license, least privilege, replay, "
            "real-sample reconciliation, approval and rollback required"
        ),
    }

    leaves = [
        capability
        for domain in snapshot["domains"]
        for capability in domain["capabilities"]
    ]
    assert len({item["id"] for item in leaves}) == len(leaves)
    assert all(item["inputs"] and item["outputs"] and item["technology"] for item in leaves)
    assert all(item["controls"] and item["markets"] and item["platforms"] for item in leaves)
    assert {item["status"] for item in leaves} <= {
        "implemented",
        "ready",
        "gated",
        "research_only",
    }
    assert any(item["id"] == "global_platform_adapters" for item in leaves)
    assert any(item["id"] == "image_to_video" for item in leaves)
    assert any(item["id"] == "full_cost_cm3" for item in leaves)


def test_atlas_point_line_surface_graph_closes_every_reference_and_control_boundary():
    snapshot = runtime.cross_border_capability_atlas.snapshot()
    graph = snapshot["operating_graph"]

    assert graph["contract_id"] == "kjds-cross-border-operating-graph-v1"
    assert graph["model"] == "point-line-surface"
    assert tuple(graph["model_definition"]) == ("point", "line", "surface")

    points = graph["atomic_points"]
    streams = graph["value_streams"]
    surfaces = graph["operating_surfaces"]
    point_ids = {point["id"] for point in points}
    stream_ids = {stream["id"] for stream in streams}

    assert len(point_ids) == len(points)
    assert len(stream_ids) == len(streams)
    assert len({surface["id"] for surface in surfaces}) == len(surfaces)
    assert all(point["value_stream_ids"] for point in points)
    assert all(set(point["value_stream_ids"]) <= stream_ids for point in points)
    assert all(
        point["input_contract"]
        and point["output_contract"]
        and point["evidence_gate"]
        and point["failure_queue"]
        and point["readback"]
        and point["kpi"]
        and point["owner"]
        and point["reviewer"]
        for point in points
    )
    assert all(
        set(stream["stage_point_ids"] + stream["supporting_point_ids"]) <= point_ids
        and stream["entry_gate"]
        and stream["exit_gate"]
        and stream["object_transitions"]
        and stream["exceptions"]
        and stream["human_takeover"]
        for stream in streams
    )
    assert all(
        set(surface["value_stream_ids"]) <= stream_ids
        and set(surface["focus_point_ids"]) <= point_ids
        and surface["dimensions"]
        and surface["decisions"]
        and surface["truth_owner"]
        and surface["alerts"]
        and surface["write_boundary"]
        for surface in surfaces
    )
    assert {
        "trend_to_opportunity",
        "opportunity_to_supplier",
        "supplier_to_unit_economics",
        "product_to_passport",
        "passport_to_content",
        "content_to_listing",
        "listing_to_publish",
        "publish_to_growth",
        "demand_to_replenishment",
        "order_to_delivery",
        "delivery_to_return_support",
        "settlement_to_reconciliation",
        "signal_to_experiment",
        "exception_to_human_control",
    } == stream_ids
    assert {
        point["evidence_tier"]
        for point in points
        if point["source_kind"] == "linkfox_public_C"
    } == {"C"}
    assert not any(
        point["status"] == "implemented"
        for point in points
        if point["source_kind"] == "linkfox_public_C"
    )


def test_every_point_line_and_surface_resolves_to_a_dedicated_operating_workspace():
    graph = runtime.cross_border_capability_atlas.snapshot()["operating_graph"]
    valid_domain_workspaces = {
        "overview",
        "data",
        "research",
        "products",
        "sourcing",
        "growth",
        "finance",
        "science",
        "governance",
        "system",
        "evidenceops",
    }

    assert all(
        point["workspace"] == f"/operations/points/{point['id']}"
        and point["workspace_id"] in valid_domain_workspaces
        for point in graph["atomic_points"]
    )
    assert all(
        stream["workspace"] == f"/operations/lines/{stream['id']}"
        for stream in graph["value_streams"]
    )
    assert all(
        surface["workspace"] == f"/operations/surfaces/{surface['id']}"
        for surface in graph["operating_surfaces"]
    )


def test_atlas_snapshot_is_a_defensive_copy():
    first = runtime.cross_border_capability_atlas.snapshot()
    first["domains"][0]["capabilities"][0]["status"] = "implemented"
    first["operating_graph"]["atomic_points"][0]["owner"] = "client"
    second = runtime.cross_border_capability_atlas.snapshot()

    assert second["domains"][0]["capabilities"][0]["status"] == "ready"
    assert second["operating_graph"]["atomic_points"][0]["owner"] != "client"


def test_atlas_rejects_promoted_linkfox_authority(tmp_path):
    registry = runtime.cross_border_capability_atlas.registry.copy()
    registry["source_policy"] = {
        **registry["source_policy"],
        "linkfox_evidence_tier": "A",
    }
    path = tmp_path / "unsafe-atlas.json"
    path.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(CapabilityAtlasError, match="C-tier"):
        CrossBorderCapabilityAtlas(path)


def test_atlas_rejects_dangling_value_stream_point(tmp_path):
    registry = json.loads(json.dumps(runtime.cross_border_capability_atlas.registry))
    registry["operating_graph"]["value_streams"][0]["stage_point_ids"].append(
        "missing-point"
    )
    path = tmp_path / "dangling-atlas.json"
    path.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(CapabilityAtlasError, match="duplicate or unknown"):
        CrossBorderCapabilityAtlas(path)


def test_atlas_rejects_implemented_linkfox_public_observation(tmp_path):
    registry = json.loads(json.dumps(runtime.cross_border_capability_atlas.registry))
    public_point = next(
        point
        for point in registry["operating_graph"]["atomic_points"]
        if point["source_kind"] == "linkfox_public_C"
    )
    public_point["status"] = "implemented"
    path = tmp_path / "promoted-public-atlas.json"
    path.write_text(json.dumps(registry, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(CapabilityAtlasError, match="promotes a public observation"):
        CrossBorderCapabilityAtlas(path)

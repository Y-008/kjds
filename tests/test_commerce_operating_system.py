from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from apps.control_plane.commerce_operating_system import (
    CommerceOperatingSystem,
)
from apps.control_plane.security import AuthenticationFailure, Principal


class TruthStub:
    def snapshot(self, **_kwargs):
        return {
            "snapshot_sha256": "truth-hash",
            "scope": {
                "entity_scope": {
                    "status": "ready",
                    "entity_ref": "entity-a",
                    "authority_sha256": "a" * 64,
                }
            },
            "contribution_views": {
                "settlement_contribution": {"status": "no_data"},
                "cash_contribution": {"status": "no_data"},
            },
            "source_gaps": [],
        }


class BatchStub:
    def __init__(self, counts=None):
        self.counts = counts or {}

    def latest(self, *, store_ref):
        return {
            "store_ref": store_ref,
            "state": "no_data" if not self.counts else "partial",
            "counts": self.counts,
            "candidates": [],
            "blockers": ["fifteen_component_cost_evidence_incomplete"],
            "snapshot_sha256": "batch-hash",
            "evidence_id": "evd-batch",
        }

    def latest_scoped(self, *, store_ref, **_kwargs):
        return self.latest(store_ref=store_ref)

    def market_radar(
        self,
        *,
        principal,
        entity_scope,
        store_ref,
        as_of,
        **_kwargs,
    ):
        return {
            "contract_id": "kjds-scoped-market-radar-v1",
            "status": "ready" if self.counts else "no_data",
            "as_of": as_of.isoformat(),
            "scope": {
                "tenant_ref": principal.tenant_ref,
                "entity_ref": entity_scope["entity_ref"],
                "store_ref": store_ref,
                "scope_grant_authority_sha256": entity_scope["authority_sha256"],
            },
            "query": {
                "source_grades": ["A", "B", "C"],
                "target_purchase_quantity": 3,
                "currency_conversion_performed": False,
            },
            "counts": {
                "observed_listings": self.counts.get("observed_listings", 0),
                "unique_exact_identities": self.counts.get("unique_exact_identities", 0),
                "own_listing_rows": self.counts.get("own_listings", 0),
                "competitor_listing_rows": self.counts.get("competitor_listings", 0),
                "supplier_option_rows": self.counts.get("supplier_observed", 0),
                "checkout_comparable_at_target": self.counts.get("checkout_cost_eligible", 0),
                "unresolved_or_filtered_rows": 0,
            },
            "cohorts": [],
            "source_gaps": [],
            "blockers": [],
            "control_envelope": {
                "read_only": True,
                "candidate_scoring_performed": False,
                "sales_inferred": False,
                "supplier_offer_created": False,
                "actual_cost_created": False,
                "external_write_allowed": False,
            },
            "snapshot_sha256": "market-radar-hash",
        }


class ErpStub:
    def __init__(self, counts=None, configured=False):
        self.counts = counts or {
            "profit_qualified": 0,
            "succeeded": 0,
        }
        self.configured = configured

    def workspace(self, *, tenant_ref, store_ref):
        return {
            "tenant_ref": tenant_ref,
            "store_ref": store_ref,
            "state": "no_data",
            "counts": self.counts,
            "connector": {"configured": self.configured},
            "blockers": ["no_profit_qualified_candidate"],
            "syncs": [],
        }

    def workspace_scoped(
        self,
        *,
        principal,
        store_ref,
        **_kwargs,
    ):
        return self.workspace(
            tenant_ref=principal.tenant_ref,
            store_ref=store_ref,
        )


class AnalyticsStub:
    def __init__(self, pipeline=None):
        self.pipeline = pipeline or []

    def snapshot(self, *, store_ref, **_kwargs):
        return {
            "store_ref": store_ref,
            "snapshot_sha256": "analytics-hash",
            "pipeline": self.pipeline,
            "data_gaps": ["真实订单与结算缺失"],
        }


class WorkbenchStub:
    def snapshot(self, *, limit, **_kwargs):
        assert limit == 100
        return {
            "snapshot_sha256": "workbench-hash",
            "work_items": [],
        }


class MediaStub:
    def __init__(self, manifests=0):
        self.manifests = manifests

    def snapshot(self):
        return {
            "snapshot_sha256": "media-hash",
            "status": "ready" if self.manifests else "no_data",
            "summary": {
                "asset_count": self.manifests,
                "execution_count": self.manifests,
                "failed_count": 0,
                "blocked_count": 0,
                "manifest_count": self.manifests,
            },
            "templates": [
                {
                    "id": "ozon-retouch-v1",
                    "kind": "image",
                }
            ],
            "control_envelope": {
                "listing_requires_all_qa_passed": True,
                "external_marketplace_write_allowed": False,
            },
        }

    def snapshot_scoped(self, **_kwargs):
        return self.snapshot()


class ProductContentStub:
    def __init__(
        self,
        *,
        products=0,
        passports=0,
        content_drafts=0,
        media_qa=0,
    ):
        self.products = products
        self.passports = passports
        self.content_drafts = content_drafts
        self.media_qa = media_qa

    def project(
        self,
        *,
        principal,
        entity_scope,
        store_ref,
        as_of,
    ):
        assert entity_scope["entity_ref"] == "entity-a"
        payload = {
            "contract_id": "kjds-scoped-product-content-v1",
            "status": "ready" if self.content_drafts else "partial",
            "as_of": as_of.isoformat(),
            "scope": {
                "tenant_ref": principal.tenant_ref,
                "entity_ref": entity_scope["entity_ref"],
                "store_ref": store_ref,
                "scope_grant_authority_sha256": entity_scope["authority_sha256"],
            },
            "products": [],
            "counts": {
                "included_products": self.products,
                "approved_passport_sets": self.passports,
                "content_draft_ready": self.content_drafts,
                "media_qa_ready": self.media_qa,
                "listing_approval_plan_ready": 0,
            },
            "source_gaps": ([] if self.content_drafts else ["approved_passports_incomplete"]),
            "blockers": [],
            "control_envelope": {
                "read_only": True,
                "raw_product_content_read": True,
                "content_draft_allowed": bool(self.content_drafts),
                "listing_draft_allowed": False,
                "approval_created": False,
                "permit_created": False,
                "external_write_allowed": False,
            },
            "snapshot_sha256": "product-content-hash",
        }
        return payload


class IntelligenceSourcesStub:
    def snapshot(
        self,
        *,
        principal,
        entity_scope,
        store_ref,
        as_of,
    ):
        ready = entity_scope.get("status") == "ready"
        return {
            "contract_id": ("kjds-intelligence-source-adapter-authority-v1"),
            "status": "ready" if ready else "no_data",
            "as_of": as_of.isoformat(),
            "scope": {
                "tenant_ref": principal.tenant_ref,
                "entity_ref": entity_scope.get("entity_ref"),
                "store_ref": store_ref,
                "scope_grant_authority_sha256": entity_scope.get("authority_sha256"),
            },
            "adapters": [
                {
                    "adapter_id": "allowed-public-1688-observation-v1",
                    "status": "implemented",
                    "max_source_grade": "C",
                    "semantic_authority": ("supplier_market_observation_only"),
                }
            ],
            "counts": {
                "implemented": 3,
                "contract_only": 1,
                "external_write_enabled": 0,
            },
            "source_gaps": ([] if ready else ["entity_scope_authority_missing"]),
            "control_envelope": {
                "capture_requires_current_entity_scope": True,
                "capture_requires_independent_evidence_binding": True,
                "supplier_offer_created": False,
                "actual_cost_created": False,
                "sales_fact_inferred": False,
                "external_write_allowed": False,
            },
            "snapshot_sha256": "intelligence-sources-hash",
        }


class ReadPilotsStub:
    CONTRACT_ID = "kjds-scoped-read-only-pilots-v1"

    @staticmethod
    def _result(values, key):
        entity_scope = values["entity_scope"]
        ready = entity_scope.get("status") == "ready"
        return {
            "contract_id": ReadPilotsStub.CONTRACT_ID,
            "status": "no_data",
            "scope": {
                "tenant_ref": values["principal"].tenant_ref,
                "entity_ref": (entity_scope.get("entity_ref") if ready else None),
                "store_ref": values["store_ref"],
                "scope_grant_authority_sha256": (entity_scope.get("authority_sha256") if ready else None),
            },
            "items": [],
            "counts": {key: 0},
            "source_gaps": [f"scoped_read_only_pilot_{key}_not_available"],
            "external_write_allowed": False,
            "snapshot_sha256": f"read-pilot-{key}-hash",
        }

    def list(self, **values):
        return self._result(values, "pilots")

    def list_runs(self, **values):
        return self._result(values, "runs")


class ReadClaimsStub:
    CONTRACT_ID = "kjds-scoped-read-only-claims-v1"

    def list(self, **values):
        entity_scope = values["entity_scope"]
        ready = entity_scope.get("status") == "ready"
        return {
            "contract_id": self.CONTRACT_ID,
            "status": "no_data",
            "as_of": values["as_of"].isoformat(),
            "scope": {
                "tenant_ref": values["principal"].tenant_ref,
                "entity_ref": (entity_scope.get("entity_ref") if ready else None),
                "store_ref": values["store_ref"],
                "scope_grant_authority_sha256": (entity_scope.get("authority_sha256") if ready else None),
            },
            "items": [],
            "counts": {
                "claims": 0,
                "pending_review": 0,
                "accepted": 0,
                "rejected": 0,
                "authority_blocked": 0,
            },
            "source_gaps": ["scoped_read_only_claim_not_available"],
            "legacy_rows_inferred": False,
            "formal_fact_promoted": False,
            "external_write_allowed": False,
            "snapshot_sha256": "read-claims-hash",
        }


class NativeParityStub:
    def __init__(self, items):
        self.items = items

    def project(self, **_values):
        return {
            "contract_id": "native-parity-acceptance-workspace.v1",
            "status": "ready" if self.items else "no_data",
            "counts": {"items": len(self.items)},
            "items": self.items,
            "snapshot_sha256": "native-parity-hash",
            "control_envelope": {"external_write_allowed": False},
        }


def service(
    *,
    counts=None,
    erp_counts=None,
    pipeline=None,
    manifests=0,
    native_parity=None,
):
    return CommerceOperatingSystem(
        truth_governance=TruthStub(),
        batch_opportunity=BatchStub(counts),
        profit_erp_sync=ErpStub(erp_counts),
        operating_analytics=AnalyticsStub(pipeline),
        operating_workbench=WorkbenchStub(),
        media_workbench=MediaStub(manifests),
        product_content=ProductContentStub(),
        intelligence_source_adapters=IntelligenceSourcesStub(),
        scoped_read_only_pilots=ReadPilotsStub(),
        scoped_read_only_claims=ReadClaimsStub(),
        native_parity_acceptance=native_parity,
    )


def principal(stores=frozenset({"ozon-primary"})):
    return Principal(
        "operator-a",
        frozenset({"operator"}),
        "tenant-a",
        stores,
    )


def test_no_data_is_not_presented_as_complete_erp_coverage():
    result = service().workspace(
        principal=principal(),
        store_ref="ozon-primary",
        as_of="2026-07-27T12:00:00Z",
    )

    assert result["status"] == "no_data"
    assert result["current_stage"]["id"] == "observe"
    assert result["current_stage"]["status"] == "no_data"
    assert result["completion_claim"] == {
        "benchmark_business_flows_fully_covered": False,
        "benchmark_products_are_runtime_dependencies": False,
        "real_profit_loop_complete": False,
        "automatic_listing_count_is_success_metric": False,
        "success_metric": ("reconciled cash CM3 + controlled learning + reversible execution"),
    }
    assert result["outcome"]["actual_profit_claimed"] is False
    read_pilots = result["read_only_pilots"]
    assert {key: value for key, value in read_pilots.items() if key != "snapshot_sha256"} == {
        "contract_id": "kjds-scoped-read-only-pilots-v1",
        "status": "no_data",
        "scope": {
            "tenant_ref": "tenant-a",
            "entity_ref": "entity-a",
            "store_ref": "ozon-primary",
            "scope_grant_authority_sha256": "a" * 64,
        },
        "counts": {"pilots": 0, "runs": 0},
        "source_gaps": [
            "scoped_read_only_pilot_pilots_not_available",
            "scoped_read_only_pilot_runs_not_available",
        ],
        "legacy_rows_inferred": False,
        "external_write_allowed": False,
    }
    assert len(read_pilots["snapshot_sha256"]) == 64
    read_claims = result["read_only_claims"]
    assert read_claims["counts"]["claims"] == 0
    assert read_claims["legacy_rows_inferred"] is False
    assert read_claims["formal_fact_promoted"] is False
    assert read_claims["external_write_allowed"] is False
    assert result["control_envelope"]["external_writes"] is False


def test_real_counts_advance_only_the_matching_native_stages():
    result = service(
        counts={
            "observed_listings": 120,
            "unique_exact_identities": 30,
            "exact_identity_matched": 10,
            "fully_costed_candidates": 4,
            "downside_positive": 3,
            "content_ready": 1,
            "published": 0,
            "ordered": 0,
            "settled_proven": 0,
        },
        erp_counts={"profit_qualified": 3, "succeeded": 1},
        manifests=1,
    ).workspace(
        principal=principal(),
        store_ref="ozon-primary",
        as_of="2026-07-27T12:00:00Z",
    )

    stages = {item["id"]: item for item in result["stages"]}
    assert stages["observe"]["status"] == "completed"
    assert stages["identity"]["status"] == "completed"
    assert stages["qualify"]["status"] == "completed"
    assert stages["item_draft"]["status"] == "completed"
    assert stages["content"]["status"] == "completed"
    assert stages["listing_approval"]["status"] == ("ready_for_internal_action")
    assert stages["publish"]["status"] == "blocked"
    assert result["current_stage"]["id"] == "listing_approval"


def test_global_media_and_generic_execution_do_not_advance_candidate():
    result = service(
        counts={
            "observed_listings": 1,
            "exact_identity_matched": 1,
            "fully_costed_candidates": 1,
            "downside_positive": 1,
        },
        erp_counts={"profit_qualified": 1, "succeeded": 1},
        manifests=3,
        pipeline=[
            {"id": "execution", "value": 9},
            {"id": "observation", "value": 7},
        ],
    ).workspace(
        principal=principal(),
        store_ref="ozon-primary",
        as_of="2026-07-27T12:00:00Z",
    )

    stages = {item["id"]: item for item in result["stages"]}
    assert stages["content"]["status"] == "ready_for_internal_action"
    assert stages["listing_approval"]["status"] == "blocked"
    assert stages["fulfill"]["qualified_record_count"] == 0


def test_benchmarks_are_not_connectors_or_runtime_dependencies():
    result = service().workspace(
        principal=principal(),
        store_ref="ozon-primary",
        as_of="2026-07-27T12:00:00Z",
    )
    rows = {item["benchmark_id"]: item for item in result["benchmark_coverage"]}

    assert set(rows) == {
        "seerfar",
        "selling51_erp",
        "miaoshou_erp",
        "mango_erp",
        "dianxiaomi_erp",
        "maozierp",
        "lizhi_ozon_assistant",
        "linkfox",
    }
    assert rows["selling51_erp"]["display_name"] == "无忧易售"
    assert rows["dianxiaomi_erp"]["display_name"] == "店小秘 ERP"
    assert rows["seerfar"]["baseline_requirement"] == ("must_have_native_parity")
    assert rows["seerfar"]["safe_capability_omission_allowed"] is False
    assert rows["seerfar"]["mapping_is_not_implementation"] is True
    assert rows["linkfox"]["comparison_only"] is True
    assert rows["linkfox"]["runtime_dependency"] is False
    assert rows["linkfox"]["integration_required"] is False
    assert all(
        item["native_verified_capability_ids"] == []
        and item["native_verified_count"] == 0
        and item["coverage_status"] == "gaps_remain"
        for item in rows.values()
    )
    assert all(
        item["implementation_status"] == "implemented_unverified" and item["acceptance_status"] == "not_proven"
        for item in result["capabilities"]
    )
    assert all(
        item["implementation_status"] == "implemented_unverified"
        and item["acceptance_status"] == "not_proven"
        and item["verified_capability_count"] == 0
        for item in result["native_architecture"]
    )
    assert "content_and_media" in rows["linkfox"]["benchmark_capability_ids"]
    assert result["benchmark_baseline_policy"]["requirement"] == ("must_have_native_parity")
    assert result["benchmark_baseline_policy"]["safe_capability_omission_allowed"] is False
    assert all(
        item["native_gap_capability_ids"]
        == sorted(set(item["benchmark_capability_ids"]) - set(item["native_verified_capability_ids"]))
        for item in rows.values()
    )
    maozi = rows["maozierp"]["workflow_mapping"]
    assert maozi["mapping_status"] == "mapped_not_implemented"
    assert maozi["observed_capability_count"] == 28
    assert maozi["mapped_count"] == 28
    assert maozi["unmapped_count"] == 0
    assert maozi["adoption_summary"] == {
        "adapt": 18,
        "deepen": 7,
        "replace": 2,
        "reject": 1,
    }
    assert maozi["implementation_is_not_claimed"] is True
    assert maozi["external_write_allowed"] is False
    capabilities = {item["id"]: item for item in maozi["capabilities"]}
    assert capabilities["cookie_binding"]["adoption"] == "reject"
    assert capabilities["cookie_binding"]["implementation_status"] == ("prohibited")
    assert capabilities["one_click_multi_store_listing"]["implementation_status"] == "gated"
    assert capabilities["editable_ai_listing"]["kjds_target"].startswith("Versioned Russian content draft")
    assert len(maozi["snapshot_sha256"]) == 64
    assert result["source_snapshots"]["maozierp_workflow_benchmark"] == (maozi["snapshot_sha256"])
    assert all(
        item["input_snapshot_hashes"]["competitive_benchmarks"] == maozi["snapshot_sha256"]
        for item in result["agent_team"]
    )


def test_native_parity_projection_does_not_upgrade_family_from_one_provider():
    accepted = {
        "scope": {
            "provider_id": "dianxiaomi_erp",
            "capability_id": "listing_management",
            "capability_version": "1",
        },
        "state": "verified_native",
        "verified_native": True,
        "snapshot_sha256": "accepted-listing-hash",
    }
    result = service(native_parity=NativeParityStub([accepted])).workspace(
        principal=principal(),
        store_ref="ozon-primary",
        as_of="2026-07-27T12:00:00Z",
    )
    providers = {item["benchmark_id"]: item for item in result["benchmark_coverage"]}
    capabilities = {item["id"]: item for item in result["capabilities"]}

    assert providers["dianxiaomi_erp"]["native_verified_capability_ids"] == ["listing_management"]
    assert providers["mango_erp"]["native_verified_capability_ids"] == []
    assert capabilities["listing_management"]["verified_native"] is False
    assert capabilities["listing_management"]["acceptance_status"] == ("gated")
    assert capabilities["listing_management"]["acceptance_provider_count"] == 1
    assert capabilities["listing_management"]["expected_acceptance_provider_count"] > 1
    assert capabilities["orders_and_returns"]["acceptance_status"] == ("not_proven")
    assert result["completion_claim"]["benchmark_business_flows_fully_covered"] is False
    assert result["source_snapshots"]["native_parity_acceptance"] == ("native-parity-hash")


def test_maozierp_workflow_projection_fails_closed_on_registry_drift(
    tmp_path,
):
    operating_system = service()
    payload = json.loads(operating_system.maozierp_benchmark_path.read_text(encoding="utf-8"))
    payload["coverage"]["mapped_count"] = 27
    drifted = tmp_path / "maozierp.json"
    drifted.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    operating_system.maozierp_benchmark_path = drifted

    with pytest.raises(ValueError, match="mapped capability count drift"):
        operating_system.workspace(
            principal=principal(),
            store_ref="ozon-primary",
            as_of="2026-07-27T12:00:00Z",
        )


def test_native_architecture_and_agent_team_own_the_business_logic():
    result = service().workspace(
        principal=principal(),
        store_ref="ozon-primary",
        as_of="2026-07-27T12:00:00Z",
    )

    modules = {item["module_id"]: item for item in result["native_architecture"]}
    assert {
        "market_intelligence",
        "pim",
        "sourcing",
        "profit_pricing",
        "content_listing",
        "oms_crm",
        "inventory_wms",
        "growth",
        "organization",
        "agent_operations",
    } == set(modules)
    assert all(item["native_kjds_owner"] for item in modules.values())
    assert not any(item["third_party_erp_dependency"] for item in modules.values())

    agents = result["agent_team"]
    assert len(agents) == 12
    assert all(item["human_review_required"] for item in agents)
    assert not any(item["can_approve_own_output"] for item in agents)
    assert not any(item["can_issue_permit"] for item in agents)
    assert not any(item["external_write_allowed"] for item in agents)

    factory = result["ai_content_factory"]
    assert factory["competitor_asset_copy_allowed"] is False
    assert factory["listing_reference_requires_all_qa_passed"] is True
    assert "Delivery Manifest" in factory["outputs"]


def test_product_passport_content_and_listing_plan_are_scoped_and_locked():
    operating_system = CommerceOperatingSystem(
        truth_governance=TruthStub(),
        batch_opportunity=BatchStub(),
        profit_erp_sync=ErpStub(),
        operating_analytics=AnalyticsStub(),
        operating_workbench=WorkbenchStub(),
        media_workbench=MediaStub(),
        product_content=ProductContentStub(
            products=2,
            passports=1,
            content_drafts=1,
            media_qa=1,
        ),
        intelligence_source_adapters=IntelligenceSourcesStub(),
    )

    result = operating_system.workspace(
        principal=principal(),
        store_ref="ozon-primary",
        as_of="2026-07-27T12:00:00Z",
    )

    content = result["product_content"]
    assert content["scope"] == {
        "tenant_ref": "tenant-a",
        "entity_ref": "entity-a",
        "store_ref": "ozon-primary",
        "scope_grant_authority_sha256": "a" * 64,
    }
    assert content["counts"] == {
        "included_products": 2,
        "approved_passport_sets": 1,
        "content_draft_ready": 1,
        "media_qa_ready": 1,
        "listing_approval_plan_ready": 0,
    }
    assert content["control_envelope"]["content_draft_allowed"] is True
    assert content["control_envelope"]["listing_draft_allowed"] is False
    assert content["control_envelope"]["approval_created"] is False
    assert content["control_envelope"]["permit_created"] is False
    assert content["control_envelope"]["external_write_allowed"] is False
    assert result["source_snapshots"]["product_content"] == ("product-content-hash")


def test_intelligence_sources_are_scoped_semantic_adapters_not_erp_truth():
    result = service().workspace(
        principal=principal(),
        store_ref="ozon-primary",
        as_of="2026-07-27T12:00:00Z",
    )

    sources = result["intelligence_sources"]
    assert sources["status"] == "ready"
    assert sources["scope"]["tenant_ref"] == "tenant-a"
    assert sources["scope"]["entity_ref"] == "entity-a"
    assert sources["counts"] == {
        "implemented": 3,
        "contract_only": 1,
        "external_write_enabled": 0,
    }
    assert sources["adapters"][0]["semantic_authority"] == ("supplier_market_observation_only")
    assert sources["control_envelope"]["supplier_offer_created"] is False
    assert sources["control_envelope"]["actual_cost_created"] is False
    assert sources["control_envelope"]["sales_fact_inferred"] is False
    assert sources["control_envelope"]["external_write_allowed"] is False
    assert result["source_snapshots"]["intelligence_sources"] == ("intelligence-sources-hash")
    assert result["market_radar"]["contract_id"] == ("kjds-scoped-market-radar-v1")
    assert result["market_radar"]["control_envelope"]["candidate_scoring_performed"] is False
    assert result["market_radar"]["control_envelope"]["external_write_allowed"] is False
    assert result["source_snapshots"]["market_radar"] == ("market-radar-hash")


def test_fixed_as_of_produces_stable_snapshot_and_cross_store_fails():
    operating_system = service()
    kwargs = {
        "principal": principal(),
        "store_ref": "ozon-primary",
        "as_of": "2026-07-27T12:00:00Z",
    }
    first = operating_system.workspace(**kwargs)
    second = operating_system.workspace(**kwargs)
    assert first["snapshot_sha256"] == second["snapshot_sha256"]

    try:
        operating_system.workspace(
            principal=principal(),
            store_ref="other-store",
            as_of="2026-07-27T12:00:00Z",
        )
    except PermissionError as exc:
        assert "not authorized" in str(exc)
    else:
        raise AssertionError("cross-store access must fail")


def test_missing_entity_never_reads_unscoped_commerce_sources():
    class NoEntityTruth(TruthStub):
        def snapshot(self, **_kwargs):
            value = super().snapshot(**_kwargs)
            value["scope"]["entity_scope"] = {
                "status": "no_data",
                "entity_ref": None,
                "authority_sha256": None,
            }
            value["source_gaps"] = ["entity_scope_authority_missing"]
            return value

    class MustNotRead:
        def latest_scoped(self, **_kwargs):
            raise AssertionError("batch source must not be read")

        def workspace_scoped(self, **_kwargs):
            raise AssertionError("ERP source must not be read")

        def snapshot_scoped(self, **_kwargs):
            raise AssertionError("media source must not be read")

        def project(self, **_kwargs):
            raise AssertionError("Product/content source must not be read")

    operating_system = CommerceOperatingSystem(
        truth_governance=NoEntityTruth(),
        batch_opportunity=MustNotRead(),
        profit_erp_sync=MustNotRead(),
        operating_analytics=AnalyticsStub(),
        operating_workbench=WorkbenchStub(),
        media_workbench=MustNotRead(),
        product_content=MustNotRead(),
    )

    result = operating_system.workspace(
        principal=principal(),
        store_ref="ozon-primary",
        as_of="2026-07-27T12:00:00Z",
    )

    assert result["status"] == "no_data"
    assert result["outcome"]["observed_listings"] == 0
    assert result["outcome"]["profit_qualified_for_erp"] == 0
    assert "scoped_batch_authority_missing" in result["source_gaps"]
    assert result["product_content"]["products"] == []
    assert result["product_content"]["control_envelope"]["raw_product_content_read"] is False
    assert result["control_envelope"]["external_writes"] is False


def test_commerce_os_route_rejects_anonymous_and_cross_store(monkeypatch):
    from apps.control_plane.api import app
    from apps.control_plane.runtime import runtime

    def reject(_key):
        raise AuthenticationFailure("missing", 401)

    monkeypatch.setattr(runtime.authenticator, "authenticate", reject)
    response = TestClient(app).get("/v1/commerce-os/workspace")
    assert response.status_code == 401

    monkeypatch.setattr(
        runtime.authenticator,
        "authenticate",
        lambda _key: principal(frozenset({"store-a"})),
    )
    response = TestClient(app).get("/v1/commerce-os/workspace?store_ref=store-b")
    assert response.status_code == 403

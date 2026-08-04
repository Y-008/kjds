from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from apps.control_plane.global_data_coverage import (
    COMPLETENESS_STATES,
    DIMENSIONS,
    SOURCE_FAMILIES,
    SOURCE_STATUSES,
    GlobalDataCoverageWorkspace,
    content_sha256,
)

ROOT = Path(__file__).parents[1]
REGISTRY_PATH = (
    ROOT / "docs" / "project" / "registries" / "global_source_domain_registry.json"
)


def _registry():
    return json.loads(REGISTRY_PATH.read_text("utf-8"))


def _sources(registry):
    return [
        source
        for family in registry["source_families"]
        for source in family["source_contracts"]
    ]


def test_registry_freezes_all_global_dimensions_and_thirteen_source_families():
    registry = _registry()

    assert registry["schema_version"] == "kjds-global-source-domain-registry-v1"
    assert set(registry["dimensions"]) == DIMENSIONS
    assert set(registry["status_vocabulary"]) == SOURCE_STATUSES
    assert set(registry["completeness_vocabulary"]) == COMPLETENESS_STATES
    assert {item["id"] for item in registry["source_families"]} == SOURCE_FAMILIES
    assert len(registry["source_families"]) == 13
    assert all(
        set(item["required_dimensions"]) == DIMENSIONS
        for item in registry["source_families"]
    )


def test_source_contract_ids_are_unique_and_currently_make_no_implemented_claim():
    registry = _registry()
    sources = _sources(registry)
    source_ids = [item["id"] for item in sources]

    assert len(sources) >= 50
    assert len(source_ids) == len(set(source_ids))
    assert {item["status"] for item in sources} <= SOURCE_STATUSES
    assert all(item["status"] != "implemented" for item in sources)
    assert all(item["implementation_evidence_refs"] == [] for item in sources)


def test_registry_covers_priority_global_source_contracts_without_overclaiming():
    registry = _registry()
    source_ids = {item["id"] for item in _sources(registry)}

    assert {
        "marketplace.amazon_sp_api_reports",
        "marketplace.ozon_seller",
        "marketplace.wildberries_seller",
        "marketplace.tiktok_shop",
        "customs_trade.un_comtrade",
        "customs_trade.wto_tariff_trade_data",
        "customs_trade.eurostat_comext",
        "company_registry.gleif_golden_copy",
        "company_registry.us_sec_edgar",
        "logistics.dhl_global_forwarding",
        "payments_fx_macro.ecb_exchange_rates",
        "payments_fx_macro.bank_of_russia_rates",
        "ip_patents_research.wipo_ip_statistics",
    } <= source_ids
    policy = registry["policy"]
    assert policy["registry_proves_collection"] is False
    assert policy["url_proves_implementation"] is False
    assert policy["connector_candidate_proves_implementation"] is False
    assert policy["global_label_proves_full_coverage"] is False


def test_registry_urls_are_https_evidence_references_not_implementation_proof():
    registry = _registry()

    for source in _sources(registry):
        for url in source["evidence_urls"]:
            parsed = urlparse(url)
            assert parsed.scheme == "https"
            assert parsed.hostname
            assert source["status"] != "implemented"


def test_registry_hash_and_control_boundaries_are_deterministic():
    registry = _registry()

    assert registry["content_sha256"] == content_sha256(registry)
    GlobalDataCoverageWorkspace._validate_registry(registry)
    assert registry["policy"]["formal_fact_promotion_allowed"] is False
    assert registry["policy"]["canonical_graph_write_allowed"] is False
    assert registry["policy"]["external_write_allowed"] is False
    assert registry["policy"]["raw_customer_data_retained"] is False

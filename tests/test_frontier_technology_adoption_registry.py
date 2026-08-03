import json
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

REGISTRY_PATH = (
    Path(__file__).parents[1]
    / "docs"
    / "project"
    / "registries"
    / "frontier_technology_adoption.json"
)
EVIDENCE_PATH = (
    Path(__file__).parents[1]
    / "docs"
    / "project"
    / "evidence"
    / "20260803_DOUYIN_MINDSET_AND_FRONTIER_TECH_RESEARCH.md"
)
DECISIONS = ("adopt_now", "pilot", "watch", "reject_now")
EXPECTED_ENTRY_STATES = {
    "adopt_now": "approved_to_implement",
    "pilot": "isolated_pilot_only",
    "watch": "monitor_only",
    "reject_now": "blocked",
}
REQUIRED_COVERAGE = {
    "agent_tracing",
    "agent_evals",
    "durable_workflows",
    "causal_graphrag",
    "mcp_auth",
    "mcp_tasks",
    "a2a",
    "otel_genai",
    "postgres18",
    "spiffe",
    "opa",
    "slsa",
    "cyclonedx",
    "webdriver_bidi",
    "react_19_2",
    "next_16",
    "torchao",
    "clickhouse",
    "iceberg",
}
SOURCE_HOST_SUFFIXES = {
    "a2a-protocol.org",
    "arxiv.org",
    "clickhouse.com",
    "cyclonedx.org",
    "iceberg.apache.org",
    "microsoft.com",
    "modelcontextprotocol.io",
    "nextjs.org",
    "openai.com",
    "openpolicyagent.org",
    "opentelemetry.io",
    "playwright.dev",
    "postgresql.org",
    "pytorch.org",
    "react.dev",
    "slsa.dev",
    "spiffe.io",
    "temporal.io",
    "w3.org",
}


def _load_registry():
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _entries(registry):
    return [
        (decision, item)
        for decision in DECISIONS
        for item in registry[decision]
    ]


def _is_primary_or_official_source(hostname):
    return any(
        hostname == suffix or hostname.endswith(f".{suffix}")
        for suffix in SOURCE_HOST_SUFFIXES
    )


def test_registry_has_four_decisions_and_complete_frontier_coverage():
    registry = _load_registry()

    assert registry["schema_version"] == "kjds-frontier-technology-adoption-v1"
    assert registry["as_of"] == "2026-08-03"
    assert set(registry["decision_vocabulary"]) == set(DECISIONS)
    assert all(registry[decision] for decision in DECISIONS)

    entries = _entries(registry)
    ids = [item["id"] for _, item in entries]
    coverage = {
        tag
        for _, item in entries
        for tag in item["coverage_tags"]
    }
    assert len(ids) == len(set(ids))
    assert len(entries) == 15
    assert coverage == REQUIRED_COVERAGE


def test_every_decision_has_evidence_risk_owner_review_and_two_gates():
    registry = _load_registry()
    required_fields = {
        "id",
        "coverage_tags",
        "decision",
        "decision_rationale",
        "maturity",
        "evidence_urls",
        "kjds_use_cases",
        "risks",
        "entry_gate",
        "exit_gate",
        "owner",
        "reviewed_on",
        "review_due_on",
        "control_boundary",
    }

    for decision, item in _entries(registry):
        assert required_fields <= set(item)
        assert item["decision"] == decision
        assert item["decision_rationale"]
        assert item["coverage_tags"]
        assert item["kjds_use_cases"]
        assert item["risks"]
        assert item["owner"]
        assert item["maturity"]["upstream_status"]
        assert item["maturity"]["evidence_basis"]

        reviewed_on = date.fromisoformat(item["reviewed_on"])
        review_due_on = date.fromisoformat(item["review_due_on"])
        assert reviewed_on <= review_due_on
        assert (review_due_on - reviewed_on).days <= 184
        assert date.today() <= review_due_on

        assert item["entry_gate"]["id"]
        assert item["entry_gate"]["criteria"]
        assert item["entry_gate"]["state"] == EXPECTED_ENTRY_STATES[decision]
        assert item["exit_gate"]["id"]
        assert item["exit_gate"]["criteria"]
        assert item["exit_gate"]["state"] == "not_passed"


def test_sources_are_https_and_limited_to_primary_or_official_material():
    registry = _load_registry()

    for _, item in _entries(registry):
        assert item["evidence_urls"]
        for evidence_url in item["evidence_urls"]:
            parsed = urlparse(evidence_url)
            assert parsed.scheme == "https"
            assert parsed.hostname
            assert _is_primary_or_official_source(parsed.hostname)


def test_every_registry_source_is_present_in_the_reviewed_research_ledger():
    registry = _load_registry()
    research = EVIDENCE_PATH.read_text(encoding="utf-8")

    for _, item in _entries(registry):
        for evidence_url in item["evidence_urls"]:
            assert evidence_url in research


def test_experimental_or_draft_technology_is_not_adopt_now_or_production_ready():
    registry = _load_registry()
    by_id = {item["id"]: item for _, item in _entries(registry)}
    constrained = {
        "mcp_tasks_durable_protocol": (
            "official_extension_with_draft_spec_and_uneven_sdk_support",
            "watch",
        ),
        "opentelemetry_genai_semantic_conventions": (
            "separate_evolving_genai_semantic_convention",
            "pilot",
        ),
        "webdriver_bidi_browser_provider": (
            "w3c_working_draft",
            "watch",
        ),
        "torchao_local_inference_optimization": (
            "mixed_stable_and_prototype_apis",
            "watch",
        ),
    }

    assert registry["policy"]["experimental_specifications_are_production_ready"] is False
    for item_id, (maturity, decision) in constrained.items():
        item = by_id[item_id]
        assert item["maturity"]["upstream_status"] == maturity
        assert item["decision"] == decision
        assert item["maturity"]["stable_for_kjds_production"] is False


def test_incremental_review_tracks_breaking_protocol_and_database_security_changes():
    registry = _load_registry()
    by_id = {item["id"]: item for _, item in _entries(registry)}

    mcp_auth = by_id["mcp_oauth_resource_authorization"]
    assert "2026-07-28" in mcp_auth["decision_rationale"]
    assert any("2026-07-28" in url for url in mcp_auth["evidence_urls"])

    mcp_tasks = by_id["mcp_tasks_durable_protocol"]
    assert mcp_tasks["decision"] == "watch"
    assert any("draft" in url for url in mcp_tasks["evidence_urls"])
    assert any("not wire-compatible" in risk for risk in mcp_tasks["risks"])

    otel = by_id["opentelemetry_genai_semantic_conventions"]
    assert otel["decision"] == "pilot"
    assert "separate repository" in otel["maturity"]["evidence_basis"]

    postgres = by_id["postgresql_18_rehearsal"]
    assert postgres["decision"] == "pilot"
    assert any("17.10" in criterion for criterion in postgres["entry_gate"]["criteria"])

    provenance = by_id["slsa_cyclonedx_supply_chain_evidence"]
    assert provenance["decision"] == "adopt_now"
    assert any("17.10" in criterion for criterion in provenance["exit_gate"]["criteria"])


def test_registry_reports_implemented_evidence_controls_without_promoting_production():
    registry = _load_registry()
    policy = registry["policy"]

    assert policy["registry_is_implementation_evidence"] is False
    assert policy["registry_is_production_readiness_evidence"] is False
    assert policy["default_runtime_dependency_allowed"] is False
    assert policy["external_write_allowed"] is False
    assert policy["formal_fact_promotion_allowed"] is False

    entries = _entries(registry)
    runtime_implemented = {
        item["id"]
        for _, item in entries
        if item["control_boundary"]["runtime_implemented"]
    }
    assert runtime_implemented == {
        "agent_run_tracing_and_evals",
        "postgresql_18_rehearsal",
        "slsa_cyclonedx_supply_chain_evidence",
    }
    assert all(
        item["control_boundary"]["production_dependency_allowed"] is False
        and item["control_boundary"]["external_write_allowed"] is False
        and item["control_boundary"]["formal_fact_promotion_allowed"] is False
        for _, item in entries
    )

    baseline = registry["current_kjds_baseline"]
    assert "append-only AgentRun/Trace/Eval Evidence ledger" in baseline["agent_runtime"]
    assert "17.10 to 18.4" in baseline["database"]
    assert "production runbook and independent recovery approval are UNKNOWN" in (
        baseline["database"]
    )
    assert "not_for_deployment" in baseline["release"]
    assert "hosted release signer is UNKNOWN" in baseline["release"]
    assert "Next.js 16.2.11" in baseline["web"]
    assert "ClickHouse and Iceberg are not runtime dependencies" in baseline["analytics"]

    coverage_scope = registry["coverage_scope"]
    assert "Frontier dependencies" in coverage_scope["included"]
    assert "context hygiene and checkpointing" in (
        coverage_scope["operating_practices_governed_by_adr_not_runtime_entries"]
    )


def test_scale_heavy_analytics_stays_rejected_until_measured_need_exists():
    registry = _load_registry()
    rejected = {item["id"]: item for item in registry["reject_now"]}
    expansion = rejected["clickhouse_iceberg_platform_expansion"]

    assert expansion["coverage_tags"] == ["clickhouse", "iceberg"]
    assert expansion["maturity"]["upstream_status"] == (
        "mature_platforms_without_validated_kjds_need"
    )
    assert expansion["entry_gate"]["state"] == "blocked"
    assert any(
        "Measured PostgreSQL workload" in criterion
        for criterion in expansion["entry_gate"]["criteria"]
    )

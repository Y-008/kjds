"""BAS-178 cross-module contract consistency (independent red-team anti-drift).

Locks in the mutual consistency of the BAS-178 governed social-commerce deep
modules and their registry. This is a negative contract: any future drift in
action/source-rank/platform/zero-authority/decision vocabularies fails here.
"""

from __future__ import annotations

import json
from pathlib import Path

from apps.control_plane import (
    campaign_authority,
    delivery_manifest,
    social_analysis,
    social_commerce,
    source_adoption,
)

ROOT = Path(__file__).parents[1]
SOURCE_ADOPTION_REGISTRY = (
    ROOT
    / "docs"
    / "project"
    / "registries"
    / "social_commerce_source_adoption.json"
)
SOCIAL_COMMERCE_REGISTRY = (
    ROOT
    / "docs"
    / "project"
    / "registries"
    / "social_commerce_contracts.json"
)

ZERO_AUTHORITY_KEYS = frozenset(
    {
        "formal_fact",
        "finance_entry",
        "approval",
        "permit",
        "pilot",
        "outbox",
        "canonical_graph_write",
        "dependency_install",
        "network",
        "external_write",
    }
)

BAS178_MODULES = (
    social_commerce,
    source_adoption,
    social_analysis,
    campaign_authority,
    delivery_manifest,
)


def _registry(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_cross_module_zero_authority_keys_identical():
    for module in BAS178_MODULES:
        assert frozenset(module.ZERO_AUTHORITY_KEYS) == ZERO_AUTHORITY_KEYS


def test_cross_module_zero_authority_all_false():
    for module in BAS178_MODULES:
        workspace = getattr(module, _workspace_class(module))()
        flags = _zero_authority_of(workspace)
        assert set(flags) == ZERO_AUTHORITY_KEYS
        assert all(not value for value in flags.values())


def test_action_vocabulary_identical_across_modules():
    assert frozenset(social_commerce.ALLOWED_ACTIONS) == frozenset(
        campaign_authority.ALLOWED_ACTIONS
    )
    assert len(social_commerce.ALLOWED_ACTIONS) == 11


def test_platform_vocabulary_identical_across_modules():
    assert frozenset(social_commerce.ALLOWED_PLATFORMS) == frozenset(
        social_analysis.ALLOWED_PLATFORMS
    )
    assert frozenset(social_commerce.ALLOWED_PLATFORMS) == {"xiaohongshu", "douyin"}


def test_source_rank_vocabulary_identical_across_modules():
    assert frozenset(social_commerce.ALLOWED_SOURCE_RANKS) == frozenset(
        source_adoption.SOURCE_LADDER
    )
    assert len(source_adoption.SOURCE_LADDER) == 5


def test_decision_vocabulary_matches_source_adoption_registry():
    registry = _registry(SOURCE_ADOPTION_REGISTRY)
    assert set(source_adoption.DECISIONS) == set(registry["decision_vocabulary"])
    assert set(source_adoption.DECISIONS) == {
        "preferred_path",
        "adopt_pattern",
        "pilot_isolated",
        "watch",
        "reject_runtime",
    }


def test_source_adoption_registry_ladder_aligns_on_ranks_one_and_two():
    registry = _registry(SOURCE_ADOPTION_REGISTRY)
    ladder = registry["source_ladder"]
    assert [item["rank"] for item in ladder] == [1, 2, 3, 4, 5]
    assert ladder[0]["id"] == "official_authorized_api" == source_adoption.SOURCE_LADDER[0]
    assert ladder[1]["id"] == "official_operator_export" == source_adoption.SOURCE_LADDER[1]


def test_source_adoption_registry_ladder_rank3_4_5_are_documented_aliases():
    # The operational registry uses narrower rank-3/4/5 ids than the evaluator
    # ladder. Both are semantically aligned to ADR-0090's five-rank ladder; the
    # evaluator ladder is the frozen input vocabulary. This pins that boundary.
    registry = _registry(SOURCE_ADOPTION_REGISTRY)
    registry_rank_ids = {item["id"] for item in registry["source_ladder"]}
    evaluator_rank_ids = set(source_adoption.SOURCE_LADDER)
    assert registry_rank_ids != evaluator_rank_ids
    assert "official_authorized_api" in registry_rank_ids
    assert "official_operator_export" in registry_rank_ids
    assert len(registry_rank_ids) == 5


def test_social_commerce_contracts_registry_matches_modules():
    registry = _registry(SOCIAL_COMMERCE_REGISTRY)
    assert set(registry["platforms"]) == {"xiaohongshu", "douyin"}
    assert set(registry["source_rank_ladder"]) == set(social_commerce.ALLOWED_SOURCE_RANKS)
    assert set(registry["allowed_actions"]) == set(social_commerce.ALLOWED_ACTIONS)
    assert set(registry["allowed_dimensions"]) == set(social_commerce.ALLOWED_DIMENSIONS)


def _zero_authority_of(workspace) -> dict:
    # Four BAS-178 modules expose public zero_authority(); the BAS-188 delivery
    # manifest keeps it private as _zero_authority(). Semantics are identical.
    public = getattr(workspace, "zero_authority", None)
    private = getattr(workspace, "_zero_authority", None)
    if callable(public):
        return public()
    if callable(private):
        return private()
    raise AssertionError(f"missing zero_authority on {type(workspace).__name__}")


def _workspace_class(module) -> str:
    mapping = {
        "social_commerce": "GovernedSocialCommerceIntelligenceWorkspace",
        "source_adoption": "GovernedSourceAdoptionEvaluator",
        "social_analysis": "GovernedSocialIntelligenceAnalysis",
        "campaign_authority": "GovernedCampaignAuthority",
        "delivery_manifest": "GovernedDeliveryManifestWorkspace",
    }
    name = module.__name__.split(".")[-1]
    return mapping[name]

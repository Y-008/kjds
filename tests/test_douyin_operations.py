"""OPS-DY-001 Douyin operator research & runbook contract tests (prep-only slice)."""

from __future__ import annotations

import pytest

from apps.control_plane.douyin_operations import (
    ACCOUNT_BINDING_REQUIRED,
    FALLBACK_SOURCE_RANK,
    OPERATOR_MODES,
    OUTPUT_TAXONOMY,
    PRIMARY_SOURCE_RANK,
    REAL_ACCOUNT_ADMITTED,
    REAL_WRITE_REQUIRES_READBACK,
    RESEARCH_BASELINE_DIMENSIONS,
    SOURCE_RANKS,
    ZERO_AUTHORITY_KEYS,
    DouyinOperationsError,
    GovernedDouyinOperations,
)


def _ops() -> GovernedDouyinOperations:
    return GovernedDouyinOperations()


def test_bind_source_primary_default():
    binding = _ops().bind_source()
    assert binding.status == "BOUND"
    assert binding.source_rank == PRIMARY_SOURCE_RANK
    assert binding.fallback_source_rank == FALLBACK_SOURCE_RANK
    assert binding.real_account_admitted is False
    assert binding.external_write_allowed is False


def test_bind_source_fallback():
    binding = _ops().bind_source(source_rank=FALLBACK_SOURCE_RANK)
    assert binding.source_rank == FALLBACK_SOURCE_RANK


def test_bind_source_unrecognized_rank_fail_closed():
    with pytest.raises(DouyinOperationsError):
        _ops().bind_source(source_rank="third_party_scraper")


def test_source_ranks_frozen():
    assert SOURCE_RANKS == (PRIMARY_SOURCE_RANK, FALLBACK_SOURCE_RANK)


def test_research_plan_frozen():
    plan = _ops().research_plan()
    assert plan.platform == "douyin"
    assert plan.baseline_dimensions == RESEARCH_BASELINE_DIMENSIONS
    assert len(plan.questions) == 7
    assert all(q["status"] == "FIXTURE" for q in plan.questions)
    assert plan.output_taxonomy == OUTPUT_TAXONOMY
    assert plan.synthetic_fixture is True
    assert plan.external_write_allowed is False
    assert {q["dimension"] for q in plan.questions} == set(RESEARCH_BASELINE_DIMENSIONS)


def test_content_hypotheses_frozen():
    result = _ops().content_hypotheses()
    assert len(result.hypotheses) == 3
    assert all(h["status"] == "FIXTURE" for h in result.hypotheses)
    assert result.synthetic_fixture is True
    assert result.external_write_allowed is False


def test_campaign_draft_templates_frozen():
    result = _ops().campaign_draft_templates()
    assert len(result.templates) == 3
    assert {t["format"] for t in result.templates} == {"short_video", "live", "creator_collab"}
    assert all(t["status"] == "FIXTURE" for t in result.templates)
    assert result.external_write_allowed is False


def test_operator_runbook_frozen():
    runbook = _ops().operator_runbook()
    assert runbook.modes == OPERATOR_MODES
    assert len(runbook.steps) == 6
    assert {s["mode"] for s in runbook.steps} == set(OPERATOR_MODES)
    assert runbook.real_write_requires_readback is True
    assert runbook.account_binding_required is True
    assert runbook.external_write_allowed is False


def test_adapter_resolution_loop_frozen():
    loop = _ops().adapter_resolution_loop()
    assert loop.platform == "douyin"
    assert len(loop.steps) == 5
    assert {s["phase"] for s in loop.steps} == {"detect", "quarantine", "diagnose", "retry_or_fallback", "readback"}
    assert loop.external_write_allowed is False


def test_readback_pending_verified_invalidated():
    ops = _ops()
    plan = ops.research_plan()
    assert ops.readback(plan)["readback_state"] == "PENDING"
    assert ops.readback(plan, observed=plan.plan_sha256)["readback_state"] == "VERIFIED"
    assert ops.readback(plan, observed="0" * 64)["readback_state"] == "INVALIDATED"


def test_zero_authority_all_false():
    authority = _ops().zero_authority()
    assert set(authority) == set(ZERO_AUTHORITY_KEYS)
    assert all(value is False for value in authority.values())
    assert "platform_write" in authority


def test_real_account_not_admitted():
    assert REAL_ACCOUNT_ADMITTED is False
    assert REAL_WRITE_REQUIRES_READBACK is True
    assert ACCOUNT_BINDING_REQUIRED is True


def test_readback_target_invalid_fail_closed():
    with pytest.raises(DouyinOperationsError):
        _ops().readback({"not": "a supported object"})

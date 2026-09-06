from apps.control_plane.experiment_contamination_checker import (
    check_experiment_contamination,
    evaluate_experiment_fact_admission,
)


def test_overlap_blocks_experiments_with_shared_population():
    result = check_experiment_contamination([
        {"id": "price-a", "population": ["sku-1", "sku-2"], "treatment": "a", "start_at": "2026-09-01T00:00:00Z", "end_at": "2026-09-10T00:00:00Z"},
        {"id": "creative-b", "population": ["sku-2"], "treatment": "b", "start_at": "2026-09-05T00:00:00Z", "end_at": "2026-09-12T00:00:00Z"},
    ])
    assert result.status == "blocked"
    assert "population_exposure_overlap" in result.blocked_reasons


def test_incomplete_experiment_fails_closed():
    result = check_experiment_contamination([{"id": "missing", "population": []}])
    assert result.status == "blocked"
    assert result.findings == ()


def test_unreviewed_experiment_fact_is_not_admitted_to_long_term_analytics():
    result = evaluate_experiment_fact_admission(
        {
            "experiment": {
                "experiment_id": "price-a",
                "review_eligible": False,
                "causal_evidence": [],
                "stop_rule": None,
            }
        }
    )

    assert result.status == "blocked"
    assert result.experiment_id == "price-a"
    assert result.blocked_reasons == (
        "experiment_causal_evidence_missing",
        "experiment_not_review_eligible",
        "experiment_stop_rule_missing",
    )


def test_reviewed_experiment_fact_requires_all_three_admission_controls():
    result = evaluate_experiment_fact_admission(
        {
            "experiment_context": {
                "protocol_id": "protocol-1",
                "review_eligible": True,
                "causal_evidence": ["evidence-1"],
                "stop_rule": {"metric": "cm3", "direction": "min"},
            }
        }
    )

    assert result.status == "eligible"
    assert result.experiment_id == "protocol-1"
    assert result.blocked_reasons == ()


def test_unmarked_fact_remains_backward_compatible():
    result = evaluate_experiment_fact_admission({"sku": "sku-1", "units": 2})

    assert result.status == "unmarked"
    assert result.experiment_id is None
    assert result.blocked_reasons == ()


def test_empty_nested_evidence_reference_is_not_admitted():
    result = evaluate_experiment_fact_admission(
        {
            "experiment_id": "protocol-1",
            "review_eligible": True,
            "causal_evidence": {"id": None},
            "stop_rule": {"id": "stop-1"},
        }
    )

    assert result.status == "blocked"
    assert result.blocked_reasons == ("experiment_causal_evidence_missing",)

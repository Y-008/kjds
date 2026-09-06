from apps.control_plane.experiment_contamination_checker import check_experiment_contamination


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

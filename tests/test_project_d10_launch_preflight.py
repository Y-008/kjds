from __future__ import annotations

from scripts.project_d10_launch_preflight import _hash, build_preflight


def test_d10_launch_preflight_keeps_all_downstream_stages_blocked():
    draft = {
        "offer_id": "D10-Q200",
        "draft_sha256": "d" * 64,
        "supplier_research": {
            "observed_offers": 140,
            "exact_dimension_and_color_candidates": 11,
            "shortlisted_distinct_suppliers": 5,
            "exact_purchase_candidates": 0,
            "formal_supplier_offers": 0,
        },
        "erp_defaults": {"canonical_product_id": None},
        "screening_price": {"max_purchase_price_cny": None},
        "release_blockers": ["packed_weight_and_dimensions_unknown"],
    }
    media = {
        "readiness": {
            "offer_id": "D10-Q200",
            "status": "draft_blocked",
            "blockers": ["supplier_reference_images_not_exact_variant"],
        }
    }
    checkout = {"plan_sha256": "c" * 64}
    fact_request = {
        "target_offer_id": "D10-Q200",
        "entry_count": 5,
        "minimum_independent_responses": 3,
        "entries": [
            {"response_status": "awaiting_manual_supplier_response"}
            for _ in range(5)
        ],
        "sources": {
            "checkout_plan": {"plan_sha256": "c" * 64},
            "draft": {"draft_sha256": "d" * 64},
        },
    }

    result = build_preflight(
        draft=draft,
        media=media,
        checkout=checkout,
        fact_request=fact_request,
        sources={},
    )

    unsealed = {key: value for key, value in result.items() if key != "preflight_sha256"}
    assert result["preflight_sha256"] == _hash(unsealed)
    assert result["status"] == "blocked_pre_canonical"
    assert result["current_facts"]["supplier_fact_responses"] == 0
    assert "canonical_product_not_created" in result["blockers"]
    assert "three_verified_checkout_snapshots_missing" in result["blockers"]
    assert "supplier_reference_images_not_exact_variant" in result["blockers"]
    assert "erp_review_package_missing" in result["blockers"]
    assert result["chain"][-1] == {
        "stage": "ozon_listing_write",
        "state": "not_authorized",
    }
    assert result["semantic_limits"]["erp_write_performed"] is False
    assert result["semantic_limits"]["ozon_write_performed"] is False


def test_d10_launch_preflight_rejects_fact_request_drift():
    draft = {
        "offer_id": "D10-Q200",
        "draft_sha256": "d" * 64,
    }
    fact_request = {
        "target_offer_id": "other",
        "sources": {
            "checkout_plan": {"plan_sha256": "c" * 64},
            "draft": {"draft_sha256": "d" * 64},
        },
    }

    import pytest

    with pytest.raises(ValueError, match="offer binding"):
        build_preflight(
            draft=draft,
            media={},
            checkout={"plan_sha256": "c" * 64},
            fact_request=fact_request,
            sources={},
        )

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.control_plane.security import Principal
from apps.control_plane.store_profile_intake import StoreProfileIntake

AS_OF = datetime(2026, 8, 2, 9, tzinfo=UTC)


def principal(*, tenant_ref: str = "tenant-a") -> Principal:
    return Principal(
        actor_id="operator-a",
        roles=frozenset({"operator"}),
        tenant_ref=tenant_ref,
        store_refs=frozenset({"store-a", "store-b"}),
    )


def entity_scope() -> dict:
    return {
        "status": "ready",
        "entity_ref": "entity-a",
        "authority_sha256": "a" * 64,
    }


def observation(evidence_type: str, **overrides) -> dict:
    value = {
        "evidence_ref": f"evd-{evidence_type}",
        "evidence_type": evidence_type,
        "observed_at": AS_OF - timedelta(hours=1),
        "valid_until": AS_OF + timedelta(days=2),
        "scope": {
            "tenant_ref": "tenant-a",
            "entity_ref": "entity-a",
            "store_ref": "store-a",
        },
        "data_grade": "A",
        "confidence": "0.98",
        "identity_quality": "exact",
        "variant_quality": "exact",
        "attributes": {
            "store_positioning": "category_specialist",
            "assortment_mode": "refined_operation",
            "price_band": "mid",
            "target_regions": ["RU"],
        },
        "category": {
            "category_id": "garden-saws",
            "category_name": "Garden saws",
            "ancestry": [
                {"category_id": "home-garden", "category_name": "Home and garden"},
                {"category_id": "garden-tools", "category_name": "Garden tools"},
            ],
        },
        "metrics": {
            "listing_count": "18",
            "order_count": "12",
            "cash_cm3": "160.00",
        },
    }
    value.update(overrides)
    return value


def exact_evidence() -> list[dict]:
    return [observation(evidence_type) for evidence_type in ("catalog", "listing", "order", "profit", "category")]


def propose(observations: list[dict], **overrides):
    values = {
        "principal": principal(),
        "entity_scope": entity_scope(),
        "store_ref": "store-a",
        "seller_tier": "beginner",
        "as_of": AS_OF,
    }
    values.update(overrides)
    return StoreProfileIntake().propose(observations, **values)


def test_new_store_is_honest_no_data_and_uses_the_shared_kernel() -> None:
    proposal = propose([])

    assert proposal["status"] == "no_data"
    assert proposal["seller_tier"] == "novice"
    assert proposal["quality"]["data_grade"] == "E"
    assert proposal["quality"]["confidence"] == "0.0000"
    assert proposal["store_attributes"] == ()
    assert proposal["category_role_assignments"] == ()
    assert proposal["placement_recommendations"] == ()
    assert proposal["reason_codes"] == (
        "evidence_type_coverage_incomplete",
        "store_evidence_missing",
    )
    assert proposal["control_envelope"]["same_business_kernel_for_all_seller_tiers"] is True
    assert proposal["control_envelope"]["formal_fact"] is False
    assert proposal["control_envelope"]["automatic_publish_allowed"] is False


@pytest.mark.parametrize(
    ("tier_input", "canonical"),
    [
        ("beginner", "novice"),
        ("individual", "solo"),
        ("small_team", "small_team"),
        ("mid_market", "mid_market"),
        ("enterprise", "enterprise"),
    ],
)
def test_all_seller_tiers_use_the_same_business_kernel(tier_input: str, canonical: str) -> None:
    proposal = propose([], seller_tier=tier_input)

    assert proposal["seller_tier"] == canonical
    assert proposal["policy_kernel_id"] == "kjds-store-profile-intake-kernel-v1"
    assert proposal["control_envelope"]["seller_tier_applies_to_review_envelope_only"] is True


def test_exact_evidence_produces_stable_immutable_review_only_proposal() -> None:
    first = propose(exact_evidence(), seller_tier="enterprise")
    replay = propose(list(reversed(exact_evidence())), seller_tier="enterprise")

    assert first["status"] == "ready_for_review"
    assert first["proposal_id"] == replay["proposal_id"]
    assert first["proposal_sha256"] == replay["proposal_sha256"]
    assert len(first["proposal_sha256"]) == 64
    assert first["quality"] == {
        "confidence": "0.9800",
        "data_grade": "A",
        "identity_quality": "exact",
        "variant_quality": "exact",
        "evidence_type_coverage": ("catalog", "category", "listing", "order", "profit"),
        "required_evidence_types": ("catalog", "category", "listing", "order", "profit"),
    }
    assert first["proposed_profile"]["store_positioning"] == "category_specialist"
    assert first["category_role_assignments"][0]["role"] == "primary"
    assert first["placement_recommendations"][0]["target_store_ref"] == "store-a"
    assert first["placement_recommendations"][0]["automatic_publish_allowed"] is False
    assert "segregation_of_duties_review" in {gate["gate"] for gate in first["reviewer_gates"]}
    with pytest.raises(TypeError):
        first["quality"]["data_grade"] = "E"
    detached = first.to_dict()
    detached["quality"]["data_grade"] = "E"
    assert first["quality"]["data_grade"] == "A"


def test_contradictory_signals_are_visible_and_block_profile_assignment() -> None:
    conflicting = observation(
        "listing",
        evidence_ref="evd-listing-conflict",
        attributes={
            "store_positioning": "general",
            "assortment_mode": "controlled_distribution",
            "price_band": "premium",
            "target_regions": ["RU"],
        },
    )
    proposal = propose([observation("catalog"), conflicting])

    assert proposal["status"] == "needs_review"
    assert "store_positioning" not in proposal["proposed_profile"]
    assert {item["field"] for item in proposal["contradictions"]} >= {
        "store_positioning",
        "assortment_mode",
        "price_band",
    }
    contradiction_gate = next(gate for gate in proposal["reviewer_gates"] if gate["gate"] == "contradiction_resolution")
    assert contradiction_gate["status"] == "blocked"
    assert proposal["control_envelope"]["external_write_allowed"] is False


def test_proposal_expiry_is_capped_by_evidence_freshness() -> None:
    evidence_expiry = AS_OF + timedelta(hours=2)
    proposal = propose(
        [observation("category", valid_until=evidence_expiry)],
        expires_at=AS_OF + timedelta(days=10),
    )

    assert proposal["time_window"]["expires_at"] == evidence_expiry.isoformat()
    assert proposal.is_expired(evidence_expiry - timedelta(microseconds=1)) is False
    assert proposal.is_expired(evidence_expiry) is True
    assert proposal.status_at(evidence_expiry) == "expired"


def test_derived_category_requires_and_preserves_official_ancestry() -> None:
    official = observation(
        "category",
        evidence_ref="evd-official-category",
        category={
            "category_id": "garden-tools",
            "category_name": "Garden tools",
            "ancestry": [{"category_id": "home-garden", "category_name": "Home and garden"}],
        },
    )
    derived = observation(
        "listing",
        evidence_ref="evd-derived-category",
        category={
            "category_id": "cordless-saw-content-led",
            "category_name": "Cordless saw content-led segment",
            "kind": "derived",
            "official_ancestor_category_id": "garden-tools",
            "ancestry": [
                {"category_id": "home-garden", "category_name": "Home and garden"},
                {"category_id": "garden-tools", "category_name": "Garden tools"},
            ],
        },
    )
    proposal = propose([official, derived])
    assignment = next(item for item in proposal["category_role_assignments"] if item["role"] == "derived")
    recommendation = next(
        item
        for item in proposal["placement_recommendations"]
        if item["source_category_id"] == "cordless-saw-content-led"
    )

    assert assignment["official_ancestor_category_id"] == "garden-tools"
    assert assignment["derived_category_is_official_taxonomy"] is False
    assert recommendation["target_category_id"] == "garden-tools"
    assert recommendation["placement_basis"] == "derived_advisory_under_official_ancestor"
    assert "derived_category_ancestry_review" in {gate["gate"] for gate in proposal["reviewer_gates"]}


def test_category_roles_and_eligible_cross_store_placement_share_one_kernel() -> None:
    categories = [
        observation(
            "category",
            evidence_ref=f"evd-category-{category_id}",
            category={
                "category_id": category_id,
                "category_name": category_id,
                "ancestry": [
                    {
                        "category_id": "home-garden",
                        "category_name": "Home and garden",
                    }
                ],
            },
            metrics={"order_count": order_count, "cash_cm3": "10"},
        )
        for category_id, order_count in (
            ("category-primary", "900"),
            ("category-secondary", "400"),
            ("category-tertiary", "10"),
        )
    ]
    destination = {
        "scope": {
            "tenant_ref": "tenant-a",
            "entity_ref": "entity-a",
            "store_ref": "store-b",
        },
        "evidence_refs": ["evd-store-b-profile"],
        "category_paths": [{"category_id": "category-secondary", "role": "primary"}],
    }
    proposal = propose(categories, destination_profiles=[destination])
    roles = {assignment["category_id"]: assignment["role"] for assignment in proposal["category_role_assignments"]}
    cross_store = next(
        recommendation
        for recommendation in proposal["placement_recommendations"]
        if recommendation["target_store_ref"] == "store-b"
    )

    assert roles == {
        "category-primary": "primary",
        "category-secondary": "secondary",
        "category-tertiary": "tertiary",
    }
    assert cross_store["source_category_id"] == "category-secondary"
    assert cross_store["eligible"] is True
    assert cross_store["cross_store_handoff_required"] is True
    assert cross_store["automatic_publish_allowed"] is False
    assert "destination_store_owner_review" in {gate["gate"] for gate in proposal["reviewer_gates"]}


def test_cross_store_and_cross_tenant_evidence_fail_closed() -> None:
    wrong_store = observation(
        "catalog",
        scope={
            "tenant_ref": "tenant-a",
            "entity_ref": "entity-a",
            "store_ref": "store-b",
        },
    )
    with pytest.raises(PermissionError, match="Observation scope"):
        propose([wrong_store])

    destination = {
        "scope": {
            "tenant_ref": "tenant-b",
            "entity_ref": "entity-a",
            "store_ref": "store-b",
        },
        "evidence_refs": ["evd-store-b-profile"],
        "category_paths": [{"category_id": "garden-saws", "role": "primary"}],
    }
    with pytest.raises(PermissionError, match="tenant/entity"):
        propose(exact_evidence(), destination_profiles=[destination])

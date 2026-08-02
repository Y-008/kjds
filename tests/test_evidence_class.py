from apps.control_plane.evidence_class import (
    BASIC_EVIDENCE_ROLES,
    EVIDENCE_CLASS_POLICY,
    REGULATED_CATEGORY_FLAGS,
    EvidenceClass,
    classify_evidence_class,
    contract,
    policy_for,
)


def test_explicit_evidence_class_overrides_inference():
    assert classify_evidence_class(
        evidence_class="manual_small",
        category_flags=["3c"],
        target_market="eu-de",
        operation_mode="auto",
    ) == EvidenceClass.MANUAL_SMALL


def test_regulated_category_flags_win_over_auto_and_market():
    for flag in sorted(REGULATED_CATEGORY_FLAGS):
        assert classify_evidence_class(
            category_flags=[flag],
            operation_mode="auto",
            target_market="eu-de",
        ) == EvidenceClass.REGULATED


def test_product_kind_regulated():
    assert classify_evidence_class(
        product_kind="cosmetics",
    ) == EvidenceClass.REGULATED


def test_eu_market_maps_to_eu_export():
    assert classify_evidence_class(
        target_market="eu-de",
        operation_mode="auto",
    ) == EvidenceClass.EU_EXPORT
    assert classify_evidence_class(
        target_market="europe",
    ) == EvidenceClass.EU_EXPORT


def test_auto_operation_defaults_to_auto_scale_fail_closed():
    assert classify_evidence_class(
        operation_mode="auto",
        target_market="ru",
    ) == EvidenceClass.AUTO_SCALE


def test_manual_default_is_manual_small():
    assert classify_evidence_class(
        operation_mode="manual",
        target_market="ru",
    ) == EvidenceClass.MANUAL_SMALL


def test_invalid_explicit_class_rejected():
    try:
        classify_evidence_class(evidence_class="nonsense")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_every_class_requires_six_basics():
    for _cls, policy in EVIDENCE_CLASS_POLICY.items():
        assert policy.requires_six_basics is True
        assert len(BASIC_EVIDENCE_ROLES) == 6


def test_passport_requirement_matches_operator_scenarios():
    assert (
        EVIDENCE_CLASS_POLICY[
            EvidenceClass.MANUAL_SMALL
        ].requires_full_passports
        is False
    )
    for cls in (
        EvidenceClass.AUTO_SCALE,
        EvidenceClass.REGULATED,
        EvidenceClass.EU_EXPORT,
    ):
        assert (
            EVIDENCE_CLASS_POLICY[cls].requires_full_passports is True
        )


def test_regulated_requires_certificates_and_eu_reserves_dpp_seam():
    assert (
        EVIDENCE_CLASS_POLICY[
            EvidenceClass.REGULATED
        ].regulated_certificates_required
        is True
    )
    assert (
        EVIDENCE_CLASS_POLICY[EvidenceClass.EU_EXPORT].dpp_mapping
        == "dpp-alignment-pending"
    )
    assert (
        EVIDENCE_CLASS_POLICY[
            EvidenceClass.MANUAL_SMALL
        ].dpp_mapping
        is None
    )


def test_policy_for_accepts_string_and_enum():
    assert policy_for("manual_small") == EVIDENCE_CLASS_POLICY[
        EvidenceClass.MANUAL_SMALL
    ]
    assert policy_for(EvidenceClass.AUTO_SCALE) == EVIDENCE_CLASS_POLICY[
        EvidenceClass.AUTO_SCALE
    ]


def test_contract_snapshot_is_stable():
    snapshot = contract()
    assert snapshot["contract_id"] == "kjds-evidence-class-policy-v1"
    assert snapshot["policy_version"] == "2026-08-02.1"
    assert set(snapshot["basic_evidence_roles"]) == BASIC_EVIDENCE_ROLES
    assert set(snapshot["classes"]) == {
        item.value for item in EvidenceClass
    }

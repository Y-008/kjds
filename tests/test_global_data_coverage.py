from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from apps.control_plane.global_data_coverage import (
    GlobalDataCoverageWorkspace,
    content_sha256,
)

ROOT = Path(__file__).parents[1]
FIXTURE_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "global_data_coverage"
    / "data_cov_001_bounded_universe_v1.json"
)
REGISTRY_PATH = (
    ROOT / "docs" / "project" / "registries" / "global_source_domain_registry.json"
)
CONTRACT_ROOT = ROOT / "docs" / "project" / "contracts"


def _fixture():
    return json.loads(FIXTURE_PATH.read_text("utf-8"))


def _registry():
    return json.loads(REGISTRY_PATH.read_text("utf-8"))


def _as_of(fixture):
    return datetime.fromisoformat(fixture["as_of"])


def _rehash(fixture, registry):
    registry["content_sha256"] = content_sha256(registry)
    fixture["manifest"]["registry_sha256"] = registry["content_sha256"]
    fixture["native_caps"]["content_sha256"] = content_sha256(
        fixture["native_caps"]
    )
    fixture["manifest"]["native_caps_sha256"] = fixture["native_caps"][
        "content_sha256"
    ]
    fixture["manifest"]["content_sha256"] = content_sha256(fixture["manifest"])


def _implemented(fixture, registry):
    source_id = fixture["manifest"]["source"]["source_id"]
    source = next(
        source
        for family in registry["source_families"]
        for source in family["source_contracts"]
        if source["id"] == source_id
    )
    source["status"] = "implemented"
    source["implementation_evidence_refs"] = [
        "fixture://global-data-coverage/adapter-verification-v1"
    ]
    fixture["manifest"]["source"]["source_status"] = "implemented"
    fixture["native_caps"]["source_status"] = "implemented"
    _rehash(fixture, registry)


def _workspace():
    return GlobalDataCoverageWorkspace(contract_root=CONTRACT_ROOT)


def test_contract_only_source_cannot_be_presented_as_full_coverage():
    fixture = _fixture()
    observation = _workspace().validate(
        fixture["manifest"],
        fixture["native_caps"],
        _registry(),
        _as_of(fixture),
    )

    assert observation.status == "blocked"
    assert observation.full_coverage_claim is False
    assert observation.full_coverage_claim_scope == "not_proven"
    assert "source_adapter_not_implemented" in observation.blockers
    assert "full_coverage_claim_not_proven" in observation.blockers
    assert observation.formal_fact is False
    assert observation.decision is False
    assert observation.approval is False
    assert observation.permit is False
    assert observation.pilot is False
    assert observation.outbox is False
    assert observation.canonical_graph_write is False
    assert observation.external_write is False
    assert observation.raw_source_retained is False


def test_evidenced_bounded_universe_can_make_only_its_exact_scoped_claim():
    fixture = _fixture()
    registry = _registry()
    _implemented(fixture, registry)

    observation = _workspace().validate(
        fixture["manifest"],
        fixture["native_caps"],
        registry,
        _as_of(fixture),
    )

    assert observation.status == "complete"
    assert observation.denominator_known is True
    assert observation.expected_count == 100
    assert observation.observed_count == 100
    assert observation.accepted_count == 100
    assert observation.full_coverage_claim is True
    assert observation.full_coverage_claim_scope == (
        "fixture-source-partition-window"
    )
    assert observation.coverage_gaps == ()
    assert observation.blockers == ()


def test_unknown_denominator_is_unknown_and_never_full():
    fixture = _fixture()
    registry = _registry()
    _implemented(fixture, registry)
    fixture["manifest"]["universe"].update(
        {
            "denominator_known": False,
            "expected_count": None,
            "expected_count_evidence_ref": None,
        }
    )
    fixture["manifest"]["conservation"]["expected_count"] = None
    fixture["manifest"]["coverage_claim"]["denominator_evidence_ref"] = None
    _rehash(fixture, registry)

    observation = _workspace().validate(
        fixture["manifest"],
        fixture["native_caps"],
        registry,
        _as_of(fixture),
    )

    assert observation.status == "unknown"
    assert observation.full_coverage_claim is False
    assert "source_universe_denominator_unknown" in observation.coverage_gaps


def test_bounded_universe_without_denominator_is_rejected():
    fixture = _fixture()
    fixture["manifest"]["universe"]["expected_count"] = None
    fixture["manifest"]["universe"]["expected_count_evidence_ref"] = None
    fixture["manifest"]["conservation"]["expected_count"] = None
    fixture["manifest"]["content_sha256"] = content_sha256(fixture["manifest"])

    with pytest.raises(ValueError, match="evidenced denominator"):
        _workspace().validate(
            fixture["manifest"],
            fixture["native_caps"],
            _registry(),
            _as_of(fixture),
        )


def test_candidate_cannot_masquerade_as_implemented_without_evidence():
    fixture = _fixture()
    registry = _registry()
    source = registry["source_families"][0]["source_contracts"][0]
    source["status"] = "implemented"
    fixture["manifest"]["source"]["source_status"] = "implemented"
    fixture["native_caps"]["source_status"] = "implemented"
    _rehash(fixture, registry)

    with pytest.raises(ValueError, match="implementation Evidence"):
        _workspace().validate(
            fixture["manifest"],
            fixture["native_caps"],
            registry,
            _as_of(fixture),
        )


def test_record_conservation_mismatch_is_rejected():
    fixture = _fixture()
    fixture["manifest"]["conservation"]["accepted_count"] = 99
    fixture["manifest"]["content_sha256"] = content_sha256(fixture["manifest"])

    with pytest.raises(ValueError, match="conservation failed"):
        _workspace().validate(
            fixture["manifest"],
            fixture["native_caps"],
            _registry(),
            _as_of(fixture),
        )


@pytest.mark.parametrize(
    ("mutation", "expected_gap"),
    [
        ("page", "page_coverage_incomplete"),
        ("field", "required_fields_missing"),
        ("window", "time_window_incomplete"),
        ("conflict", "source_conflicts_unresolved"),
    ],
)
def test_known_page_field_window_and_conflict_gaps_downgrade_claim(
    mutation, expected_gap
):
    fixture = _fixture()
    registry = _registry()
    _implemented(fixture, registry)
    manifest = fixture["manifest"]
    if mutation == "page":
        manifest["coverage"]["pages"].update(
            {
                "received_count": 1,
                "failed_count": 1,
                "failed_refs": ["page://fixture/2"],
                "closed": False,
            }
        )
    elif mutation == "field":
        field = manifest["coverage"]["fields"]["present"].pop()
        manifest["coverage"]["fields"]["missing"] = [field]
    elif mutation == "window":
        manifest["coverage"]["window"]["gaps"] = [
            {
                "start": "2026-07-10T00:00:00+00:00",
                "end": "2026-07-11T00:00:00+00:00",
                "reason_code": "fixture-gap",
            }
        ]
    else:
        field = manifest["coverage"]["fields"]["present"].pop()
        manifest["coverage"]["fields"]["conflicting"] = [field]
        manifest["conflicts"] = [
            {
                "conflict_ref": "conflict://fixture/1",
                "subject_ref_sha256": "d" * 64,
                "field": field,
                "valid_interval_sha256": "e" * 64,
                "value_hashes": ["1" * 64, "2" * 64],
                "resolution_status": "unresolved",
            }
        ]
    _rehash(fixture, registry)

    observation = _workspace().validate(
        manifest,
        fixture["native_caps"],
        registry,
        _as_of(fixture),
    )

    assert observation.status == "partial"
    assert observation.full_coverage_claim is False
    assert expected_gap in observation.coverage_gaps


def test_stale_snapshot_blocks_claim():
    fixture = _fixture()
    registry = _registry()
    _implemented(fixture, registry)
    fixture["manifest"]["freshness"]["status"] = "stale"
    _rehash(fixture, registry)

    observation = _workspace().validate(
        fixture["manifest"],
        fixture["native_caps"],
        registry,
        _as_of(fixture),
    )

    assert observation.status == "blocked"
    assert observation.full_coverage_claim is False
    assert "coverage_snapshot_stale" in observation.blockers


def test_checkpoint_or_content_hash_drift_fails_closed():
    fixture = _fixture()
    fixture["manifest"]["checkpoint"]["sha256"] = "f" * 64

    with pytest.raises(ValueError, match="content hash drift"):
        _workspace().validate(
            fixture["manifest"],
            fixture["native_caps"],
            _registry(),
            _as_of(fixture),
        )


def test_cross_family_source_or_capability_drift_is_rejected():
    fixture = _fixture()
    fixture["native_caps"]["source_family"] = "customs_trade"
    fixture["native_caps"]["content_sha256"] = content_sha256(
        fixture["native_caps"]
    )
    fixture["manifest"]["native_caps_sha256"] = fixture["native_caps"][
        "content_sha256"
    ]
    fixture["manifest"]["content_sha256"] = content_sha256(fixture["manifest"])

    with pytest.raises(ValueError, match="binding drift"):
        _workspace().validate(
            fixture["manifest"],
            fixture["native_caps"],
            _registry(),
            _as_of(fixture),
        )


def test_illegal_status_schema_and_native_field_are_rejected():
    fixture = _fixture()
    bad_status = copy.deepcopy(fixture)
    bad_status["manifest"]["source"]["source_status"] = "ready"
    with pytest.raises(ValidationError):
        _workspace().validate(
            bad_status["manifest"],
            bad_status["native_caps"],
            _registry(),
            _as_of(bad_status),
        )

    bad_schema = copy.deepcopy(fixture)
    bad_schema["native_caps"]["schema_version"] = "v2"
    with pytest.raises(ValidationError):
        _workspace().validate(
            bad_schema["manifest"],
            bad_schema["native_caps"],
            _registry(),
            _as_of(bad_schema),
        )

    bad_field = copy.deepcopy(fixture)
    bad_field["native_caps"]["capabilities"]["fields"].pop()
    bad_field["native_caps"]["content_sha256"] = content_sha256(
        bad_field["native_caps"]
    )
    bad_field["manifest"]["native_caps_sha256"] = bad_field["native_caps"][
        "content_sha256"
    ]
    bad_field["manifest"]["content_sha256"] = content_sha256(
        bad_field["manifest"]
    )
    with pytest.raises(ValueError, match="native capability"):
        _workspace().validate(
            bad_field["manifest"],
            bad_field["native_caps"],
            _registry(),
            _as_of(bad_field),
        )


def test_same_input_replays_the_same_observation_hash():
    fixture = _fixture()
    workspace = _workspace()
    first = workspace.validate(
        fixture["manifest"],
        fixture["native_caps"],
        _registry(),
        _as_of(fixture),
    )
    second = workspace.validate(
        fixture["manifest"],
        fixture["native_caps"],
        _registry(),
        _as_of(fixture),
    )

    assert first == second
    assert len(first.observation_sha256) == 64


def test_schemas_are_valid_and_fixture_contains_no_customer_or_secret_material():
    fixture = _fixture()
    for name in (
        "source-coverage-manifest-v1.schema.json",
        "source-native-caps-v1.schema.json",
    ):
        Draft202012Validator.check_schema(
            json.loads((CONTRACT_ROOT / name).read_text("utf-8"))
        )
    serialized = json.dumps(fixture, sort_keys=True).lower()
    assert "@" not in serialized
    assert "authorization: bearer" not in serialized
    assert "private key" not in serialized
    assert "customer_pii" not in serialized

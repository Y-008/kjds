from __future__ import annotations

import copy
import hashlib
import inspect
import json
from datetime import datetime
from pathlib import Path

import pytest

from apps.control_plane.comfy_template_benchmark import (
    EXPECTED_FIXTURE_CONTENT_SHA256,
    EXPECTED_REGISTRY_CONTENT_SHA256,
    ComfyTemplateBenchmarkContractError,
    ComfyTemplateBenchmarkScope,
    GovernedComfyTemplateBenchmarkWorkspace,
)
from apps.control_plane.content_growth import IMAGE_QA, REQUIRED_QA
from apps.control_plane.media_workbench import TEMPLATE_CATALOG

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "docs/project/registries/comfy_template_benchmark_contracts.json"
FIXTURE_PATH = ROOT / "tests/fixtures/media_agent/bas185_comfy_template_benchmark_v1.json"
CHECKED_AT = datetime.fromisoformat("2026-08-05T00:00:00+00:00")


def _load() -> tuple[dict, dict]:
    return (
        json.loads(REGISTRY_PATH.read_text(encoding="utf-8")),
        json.loads(FIXTURE_PATH.read_text(encoding="utf-8")),
    )


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _hash(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _seal(value: dict, field: str) -> None:
    payload = copy.deepcopy(value)
    payload.pop(field, None)
    value[field] = _hash(payload)


def _seal_registry(registry: dict, fixture: dict) -> None:
    _seal(registry, "content_sha256")
    fixture["registry_content_sha256"] = registry["content_sha256"]
    _seal(fixture, "content_sha256")


def _seal_fixture(fixture: dict) -> None:
    _seal(fixture, "content_sha256")


def _refresh_runtime(fixture: dict) -> None:
    runtime = fixture["runtime_receipt"]
    _seal(runtime, "receipt_sha256")
    for run in fixture["run_receipts"]:
        run["runtime_receipt_sha256"] = runtime["receipt_sha256"]
        run["environment_sha256"] = runtime["environment"]["environment_sha256"]
        _seal(run, "receipt_sha256")
    _seal_fixture(fixture)


def _refresh_environment(fixture: dict) -> None:
    environment = fixture["runtime_receipt"]["environment"]
    _seal(environment, "environment_sha256")
    _refresh_runtime(fixture)


def _refresh_run(fixture: dict, index: int) -> None:
    _seal(fixture["run_receipts"][index], "receipt_sha256")
    _seal_fixture(fixture)


def _scope(fixture: dict, **overrides: object) -> ComfyTemplateBenchmarkScope:
    values = {**fixture["scope"], **overrides, "checked_at": CHECKED_AT}
    return ComfyTemplateBenchmarkScope(**values)


def _workspace(
    *,
    registry: dict | None = None,
    fixture: dict | None = None,
    scope: ComfyTemplateBenchmarkScope | None = None,
) -> tuple[GovernedComfyTemplateBenchmarkWorkspace, dict, dict]:
    loaded_registry, loaded_fixture = _load()
    registry = copy.deepcopy(registry or loaded_registry)
    fixture = copy.deepcopy(fixture or loaded_fixture)
    workspace = GovernedComfyTemplateBenchmarkWorkspace.from_trusted_documents_for_test(
        scope=scope or _scope(fixture),
        registry=registry,
        fixture=fixture,
    )
    return workspace, registry, fixture


def _evaluate(
    workspace: GovernedComfyTemplateBenchmarkWorkspace,
    fixture: dict,
):
    return workspace.evaluate(
        fixture["template_ref"],
        fixture["fixture_ref"],
        fixture["runtime_receipt"],
        fixture["run_receipts"],
    )


def _gates(observation) -> dict[str, str]:
    return {item.gate_id: item.status for item in observation.gate_results}


def test_repository_documents_are_canonically_sealed_and_compiled() -> None:
    registry, fixture = _load()
    registry_payload = {key: value for key, value in registry.items() if key != "content_sha256"}
    fixture_payload = {key: value for key, value in fixture.items() if key != "content_sha256"}
    assert _hash(registry_payload) == registry["content_sha256"] == EXPECTED_REGISTRY_CONTENT_SHA256
    assert _hash(fixture_payload) == fixture["content_sha256"] == EXPECTED_FIXTURE_CONTENT_SHA256
    assert fixture["registry_content_sha256"] == registry["content_sha256"]


def test_baseline_is_verified_synthetic_observation_but_never_admitted() -> None:
    registry, fixture = _load()
    workspace = GovernedComfyTemplateBenchmarkWorkspace(
        scope=_scope(fixture),
        repository_root=ROOT,
    )
    observation = _evaluate(workspace, fixture)
    assert observation.synthetic_contract_verified is True
    assert observation.candidate_state == "not_admitted"
    assert observation.real_8gb_status == "UNKNOWN"
    assert observation.production_admitted is False
    assert observation.blockers == tuple(
        sorted(
            {
                "current_scope_authority_not_connected_in_synthetic_slice",
                "current_runtime_authority_not_connected_in_synthetic_slice",
                "independent_human_review_missing",
                "independent_license_authority_not_connected_in_synthetic_slice",
                "independent_run_authority_not_connected_in_synthetic_slice",
                "production_catalog_expansion_not_approved",
                "real_8gb_sample_missing",
                "rollback_not_exercised",
                "synthetic_contract_slice_not_production_evidence",
            }
        )
    )
    assert set(observation.unknowns) >= {
        "current_scope_authority",
        "current_runtime_authority",
        "independent_license_authority",
        "independent_run_authority",
        "real_8gb_peak_vram",
        "real_8gb_quality",
        "real_8gb_latency",
        "production_operating_cost",
        "real_8gb_sample",
    }
    assert _gates(observation) == {
        gate_id: ("blocked" if gate_id in {
            "current_scope_authority",
            "current_runtime_authority",
            "independent_license_authority",
            "independent_run_authority",
            "real_8gb_sample",
            "independent_human_review",
            "rollback",
            "production_catalog_expansion",
            "production_admission_boundary",
        } else "passed")
        for gate_id in registry["hard_gate_ids"]
    }


def test_replay_is_deterministic_and_contains_no_raw_receipt_body() -> None:
    workspace, _, fixture = _workspace()
    first = _evaluate(workspace, fixture)
    second = _evaluate(workspace, fixture)
    assert first == second
    assert first.result_sha256 == second.result_sha256
    projection = json.dumps(first.projection(), sort_keys=True)
    assert fixture["runtime_receipt"]["receipt_id"] not in projection
    assert fixture["parameter_set"]["input_image_ref"] not in projection


def test_unique_evaluate_interface_does_not_accept_workflow_json() -> None:
    workspace, _, fixture = _workspace()
    signature = inspect.signature(workspace.evaluate)
    assert tuple(signature.parameters) == (
        "template_ref",
        "fixture_ref",
        "runtime_receipt",
        "run_receipts",
    )
    with pytest.raises(TypeError):
        workspace.evaluate(
            fixture["template_ref"],
            fixture["fixture_ref"],
            fixture["runtime_receipt"],
            fixture["run_receipts"],
            workflow={"custom": "caller-controlled"},
        )


@pytest.mark.parametrize(
    "run_receipts",
    ["not-a-receipt-sequence", ["not-a-mapping"], [1], [None]],
)
def test_run_receipts_require_a_sequence_of_mappings(run_receipts: object) -> None:
    workspace, _, fixture = _workspace()
    with pytest.raises(
        ComfyTemplateBenchmarkContractError,
        match="receipts do not match the contract",
    ):
        workspace.evaluate(
            fixture["template_ref"],
            fixture["fixture_ref"],
            fixture["runtime_receipt"],
            run_receipts,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("target", ["registry", "fixture"])
def test_document_hash_drift_is_rejected(target: str) -> None:
    registry, fixture = _load()
    document = registry if target == "registry" else fixture
    document["version"] = "drift"
    with pytest.raises(ComfyTemplateBenchmarkContractError, match="content hash drift"):
        GovernedComfyTemplateBenchmarkWorkspace.from_trusted_documents_for_test(
            scope=_scope(fixture),
            registry=registry,
            fixture=fixture,
        )


def test_benchmark_registry_does_not_replace_production_template_truth() -> None:
    registry, _ = _load()
    champion = next(item for item in TEMPLATE_CATALOG if item["id"] == "ozon-retouch-v1")
    challenger = registry["template_contracts"][0]
    assert champion["status"] == "admitted"
    assert challenger["lifecycle"] == "shadow_candidate"
    assert challenger["production_admitted"] is False
    assert registry["production_truth"]["benchmark_registry_is_production_truth"] is False
    assert registry["production_truth"]["production_catalog_write_allowed"] is False


@pytest.mark.parametrize("mutation", ["custom_node", "model_download", "caller_workflow"])
def test_arbitrary_workflow_custom_node_and_model_download_are_rejected(mutation: str) -> None:
    registry, fixture = _load()
    workflow = registry["template_contracts"][0]["workflow_contract"]
    if mutation == "custom_node":
        workflow["nodes"].append({"node_id": "4", "class_type": "CustomRemoteNode", "inputs": {}})
        registry["template_contracts"][0]["node_allowlist"].append("CustomRemoteNode")
    elif mutation == "model_download":
        workflow["model_url"] = "https://invalid.example/model.bin"
    else:
        workflow["caller_workflow_json"] = {"arbitrary": True}
    registry["template_contracts"][0]["workflow_sha256"] = _hash(workflow)
    _seal_registry(registry, fixture)
    with pytest.raises(ComfyTemplateBenchmarkContractError):
        GovernedComfyTemplateBenchmarkWorkspace.from_trusted_documents_for_test(
            scope=_scope(fixture),
            registry=registry,
            fixture=fixture,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("seed", -1),
        ("seed", 2_147_483_648),
        ("target_megapixels", -0.1),
        ("target_megapixels", 4.1),
        ("upscale_method", "nearest"),
    ],
)
def test_typed_parameter_bounds_fail_closed(field: str, value: object) -> None:
    registry, fixture = _load()
    fixture["parameter_set"][field] = value
    _seal_fixture(fixture)
    workspace, _, fixture = _workspace(registry=registry, fixture=fixture)
    observation = _evaluate(workspace, fixture)
    assert _gates(observation)["typed_workflow_compiler"] == "blocked"
    assert observation.candidate_state == "not_admitted"
    assert observation.production_admitted is False


def test_extra_parameter_named_workflow_is_rejected() -> None:
    registry, fixture = _load()
    fixture["parameter_set"]["workflow"] = {"caller": "controlled"}
    _seal_fixture(fixture)
    workspace, _, fixture = _workspace(registry=registry, fixture=fixture)
    observation = _evaluate(workspace, fixture)
    assert _gates(observation)["typed_workflow_compiler"] == "blocked"


@pytest.mark.parametrize(
    ("scope_field", "value"),
    [
        ("tenant_ref", "tenant-other"),
        ("entity_ref", "entity-other"),
        ("store_ref", "store-other"),
        ("scope_grant_authority_sha256", "b" * 64),
    ],
)
def test_cross_scope_and_authority_context_drift_are_not_visible(
    scope_field: str,
    value: str,
) -> None:
    registry, fixture = _load()
    workspace, _, fixture = _workspace(
        registry=registry,
        fixture=fixture,
        scope=_scope(fixture, **{scope_field: value}),
    )
    observation = _evaluate(workspace, fixture)
    assert _gates(observation)["synthetic_scope_binding"] == "blocked"
    assert observation.runtime_receipt_sha256 is None
    assert observation.run_receipt_sha256s == ()
    assert observation.production_admitted is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("effective_at", "2026-08-05T01:00:00+00:00"),
        ("recorded_at", "2026-08-05T01:00:00+00:00"),
        ("effective_until", "2026-08-05T00:00:00+00:00"),
    ],
)
def test_stale_and_future_runtime_receipts_are_blocked(field: str, value: str) -> None:
    registry, fixture = _load()
    fixture["runtime_receipt"][field] = value
    _refresh_runtime(fixture)
    workspace, _, fixture = _workspace(registry=registry, fixture=fixture)
    observation = _evaluate(workspace, fixture)
    assert _gates(observation)["synthetic_runtime_receipt_shape"] == "blocked"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("total_vram_bytes", 16 * 1024**3),
        ("model_sha256", "b" * 64),
        ("node_bundle_sha256", "c" * 64),
    ],
)
def test_fake_8gb_model_and_node_provenance_are_blocked(field: str, value: object) -> None:
    registry, fixture = _load()
    fixture["runtime_receipt"]["environment"][field] = value
    _refresh_environment(fixture)
    workspace, _, fixture = _workspace(registry=registry, fixture=fixture)
    observation = _evaluate(workspace, fixture)
    assert _gates(observation)["synthetic_runtime_receipt_shape"] == "blocked"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("peak_allocated_vram_bytes", -1),
        ("peak_reserved_vram_bytes", 8 * 1024**3 + 1),
        ("wall_latency_ms", 8_001),
        ("oom", True),
        ("partial_failure", True),
        ("retry_count", 1),
        ("automatic_downgrade", True),
        ("included_in_aggregate", False),
    ],
)
def test_resource_failure_oom_retry_downgrade_and_sample_picking_are_blocked(
    field: str,
    value: object,
) -> None:
    registry, fixture = _load()
    fixture["run_receipts"][2][field] = value
    _refresh_run(fixture, 2)
    workspace, _, fixture = _workspace(registry=registry, fixture=fixture)
    observation = _evaluate(workspace, fixture)
    assert _gates(observation)["synthetic_run_receipt_shape"] == "blocked"
    assert observation.production_admitted is False


def test_nan_measurement_fails_closed_without_projection() -> None:
    workspace, _, fixture = _workspace()
    runtime = copy.deepcopy(fixture["runtime_receipt"])
    runtime["environment"]["total_vram_bytes"] = float("nan")
    observation = workspace.evaluate(
        fixture["template_ref"],
        fixture["fixture_ref"],
        runtime,
        fixture["run_receipts"],
    )
    assert _gates(observation)["synthetic_runtime_receipt_shape"] == "blocked"
    assert "NaN" not in json.dumps(observation.projection())


@pytest.mark.parametrize("remove_phase", ["warmup", "measurement"])
def test_missing_warmup_or_repeat_is_blocked(remove_phase: str) -> None:
    registry, fixture = _load()
    index = next(index for index, run in enumerate(fixture["run_receipts"]) if run["phase"] == remove_phase)
    fixture["run_receipts"].pop(index)
    _seal_fixture(fixture)
    workspace, _, fixture = _workspace(registry=registry, fixture=fixture)
    observation = _evaluate(workspace, fixture)
    assert _gates(observation)["synthetic_run_receipt_shape"] == "blocked"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model_license_id", "unverified-license"),
        ("node_bundle_license_id", "unverified-license"),
        ("commercial_use_allowed", False),
        ("redistribution_reviewed", False),
    ],
)
def test_license_and_provenance_gates_are_non_exchangeable(field: str, value: object) -> None:
    registry, fixture = _load()
    fixture["runtime_receipt"]["license_attestation"][field] = value
    _refresh_runtime(fixture)
    workspace, _, fixture = _workspace(registry=registry, fixture=fixture)
    observation = _evaluate(workspace, fixture)
    assert _gates(observation)["synthetic_license_sbom_shape"] == "blocked"
    assert observation.production_admitted is False


@pytest.mark.parametrize(
    ("missing_field", "expected_gate"),
    [
        ("real_8gb_sample_admitted", "real_8gb_sample"),
        ("independent_human_review_completed", "independent_human_review"),
        ("rollback_exercised", "rollback"),
        ("production_catalog_expansion_approved", "production_catalog_expansion"),
    ],
)
def test_each_admission_requirement_independently_blocks(
    missing_field: str,
    expected_gate: str,
) -> None:
    registry, fixture = _load()
    for field in (
        "real_8gb_sample_admitted",
        "independent_human_review_completed",
        "rollback_exercised",
        "production_catalog_expansion_approved",
    ):
        fixture["admission_inputs"][field] = field != missing_field
    _seal_fixture(fixture)
    workspace, _, fixture = _workspace(registry=registry, fixture=fixture)
    observation = _evaluate(workspace, fixture)
    assert _gates(observation)[expected_gate] == "blocked"
    assert {
        item.gate_id for item in observation.gate_results if item.status == "blocked"
    } == {
        "current_scope_authority",
        "current_runtime_authority",
        expected_gate,
        "independent_license_authority",
        "independent_run_authority",
        "production_admission_boundary",
    }
    assert observation.production_admitted is False


def test_even_all_synthetic_admission_booleans_cannot_admit_production() -> None:
    registry, fixture = _load()
    for field in (
        "real_8gb_sample_admitted",
        "independent_human_review_completed",
        "rollback_exercised",
        "production_catalog_expansion_approved",
    ):
        fixture["admission_inputs"][field] = True
    _seal_fixture(fixture)
    workspace, _, fixture = _workspace(registry=registry, fixture=fixture)
    observation = _evaluate(workspace, fixture)
    assert {
        item.gate_id for item in observation.gate_results if item.status == "blocked"
    } == {
        "current_scope_authority",
        "current_runtime_authority",
        "independent_license_authority",
        "independent_run_authority",
        "production_admission_boundary",
    }
    assert all(
        item.status == "passed"
        for item in observation.gate_results
        if item.gate_id
        not in {
            "current_scope_authority",
            "current_runtime_authority",
            "independent_license_authority",
            "independent_run_authority",
            "production_admission_boundary",
        }
    )
    assert observation.blockers == tuple(
        sorted(
            {
                "current_scope_authority_not_connected_in_synthetic_slice",
                "current_runtime_authority_not_connected_in_synthetic_slice",
                "independent_license_authority_not_connected_in_synthetic_slice",
                "independent_run_authority_not_connected_in_synthetic_slice",
                "synthetic_contract_slice_not_production_evidence",
            }
        )
    )
    assert set(observation.unknowns) >= {
        "current_scope_authority",
        "current_runtime_authority",
        "independent_license_authority",
        "independent_run_authority",
    }
    assert observation.synthetic_contract_verified is True
    assert observation.candidate_state == "not_admitted"
    assert observation.production_admitted is False
    assert observation.real_8gb_status == "UNKNOWN"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("quality_score_used_as_human_review", True),
        ("workflow_download_permitted", True),
    ],
)
def test_quality_score_cannot_replace_review_and_downloads_are_prohibited(
    field: str,
    value: bool,
) -> None:
    registry, fixture = _load()
    fixture["admission_inputs"][field] = value
    _seal_fixture(fixture)
    workspace, _, fixture = _workspace(registry=registry, fixture=fixture)
    observation = _evaluate(workspace, fixture)
    assert _gates(observation)["media_qa_authority"] == "blocked"
    assert observation.production_admitted is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("unsafe_secret", "sk-synthetic-canary-123456"),
        ("operator_note", "synthetic.user@example.com"),
    ],
)
def test_secret_and_customer_data_canaries_are_rejected_before_projection(
    field: str,
    value: str,
) -> None:
    workspace, _, fixture = _workspace()
    runtime = copy.deepcopy(fixture["runtime_receipt"])
    runtime[field] = value
    with pytest.raises(ComfyTemplateBenchmarkContractError, match="sensitive"):
        workspace.evaluate(
            fixture["template_ref"],
            fixture["fixture_ref"],
            runtime,
            fixture["run_receipts"],
        )


def test_runtime_and_run_receipt_hash_drift_fail_closed() -> None:
    workspace, _, fixture = _workspace()
    runtime = copy.deepcopy(fixture["runtime_receipt"])
    runtime["receipt_sha256"] = "b" * 64
    first = workspace.evaluate(
        fixture["template_ref"], fixture["fixture_ref"], runtime, fixture["run_receipts"]
    )
    assert _gates(first)["synthetic_runtime_receipt_shape"] == "blocked"
    runs = copy.deepcopy(fixture["run_receipts"])
    runs[0]["receipt_sha256"] = "c" * 64
    second = workspace.evaluate(
        fixture["template_ref"], fixture["fixture_ref"], fixture["runtime_receipt"], runs
    )
    assert _gates(second)["synthetic_run_receipt_shape"] == "blocked"


def test_media_qa_rules_are_imported_from_the_existing_authority() -> None:
    workspace, registry, fixture = _workspace()
    observation = _evaluate(workspace, fixture)
    expected = tuple(sorted(REQUIRED_QA | IMAGE_QA))
    assert observation.required_media_qa_rules == expected
    assert registry["qa_authority"]["required_rules"] == list(expected)
    assert registry["qa_authority"]["automatic_metrics_are_observations_only"] is True
    assert registry["qa_authority"]["independent_human_review_required"] is True


def test_every_side_effect_and_governance_authority_is_false() -> None:
    workspace, registry, fixture = _workspace()
    observation = _evaluate(workspace, fixture)
    assert dict(observation.side_effects) == registry["zero_authority_flags"]
    assert set(dict(observation.side_effects).values()) == {False}
    source = (ROOT / "apps/control_plane/comfy_template_benchmark.py").read_text(encoding="utf-8")
    assert "queue_workflow(" not in source
    assert "requests." not in source
    assert "ContentAssetRow" not in source

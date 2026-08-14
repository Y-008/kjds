from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

from .content_growth import IMAGE_QA, REQUIRED_QA
from .media_workbench import TEMPLATE_CATALOG

REGISTRY_PATH = Path("docs/project/registries/comfy_template_benchmark_contracts.json")
FIXTURE_PATH = Path("tests/fixtures/media_agent/bas185_comfy_template_benchmark_v1.json")
EXPECTED_REGISTRY_CONTENT_SHA256 = "dd09d28bcc4f102f1b6b6cb7ed0441fdbd0517781939d496c2ed5d6c9d8848d2"
EXPECTED_FIXTURE_CONTENT_SHA256 = "f723aef981a65a4165792b76a8888d29d87c4a9beb1b3537c47024326fdecf1a"
OBSERVATION_CONTRACT_ID = "kjds-governed-comfy-template-benchmark-observation-v1"
GIB = 1024**3

_HEX64 = re.compile(r"[0-9a-f]{64}")
_SAFE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}")
_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._-]+", re.IGNORECASE),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
)
_SENSITIVE_KEY_PARTS = frozenset(
    {
        "cookie",
        "credential",
        "customer",
        "password",
        "prompt",
        "provider_request",
        "raw_body",
        "secret",
        "token",
    }
)

_REGISTRY_FIELDS = {
    "schema_version",
    "contract_id",
    "version",
    "slice",
    "production_truth",
    "qa_authority",
    "template_contracts",
    "runtime_receipt_contract",
    "run_receipt_contract",
    "benchmark_policy",
    "hard_gate_ids",
    "zero_authority_flags",
    "content_sha256",
}
_FIXTURE_FIELDS = {
    "contract_id",
    "fixture_ref",
    "version",
    "registry_content_sha256",
    "license_class",
    "data_classification",
    "contains_customer_data",
    "contains_secrets",
    "template_ref",
    "scope",
    "data_as_of",
    "parameter_set",
    "compiled_workflow_sha256",
    "runtime_receipt",
    "run_receipts",
    "admission_inputs",
    "expected",
    "content_sha256",
}
_SCOPE_FIELDS = {
    "tenant_ref",
    "entity_ref",
    "store_ref",
    "scope_grant_authority_sha256",
}
_RUNTIME_FIELDS = {
    "contract_id",
    "receipt_id",
    "schema_version",
    "scope",
    "recorded_at",
    "effective_at",
    "effective_until",
    "environment",
    "workload",
    "license_attestation",
    "sbom_sha256",
    "receipt_sha256",
}
_ENVIRONMENT_FIELDS = {
    "gpu_descriptor",
    "total_vram_bytes",
    "driver_version",
    "cuda_version",
    "comfyui_version",
    "python_version",
    "os_profile",
    "model_artifact_id",
    "model_sha256",
    "node_bundle_id",
    "node_bundle_sha256",
    "node_registry_sha256",
    "environment_sha256",
}
_WORKLOAD_FIELDS = {
    "resolution_width",
    "resolution_height",
    "batch_size",
    "seed",
    "warmup_runs",
    "measurement_runs",
    "sample_selection_policy",
}
_LICENSE_FIELDS = {
    "model_license_id",
    "node_bundle_license_id",
    "commercial_use_allowed",
    "redistribution_reviewed",
    "attestation_sha256",
}
_RUN_FIELDS = {
    "contract_id",
    "run_id",
    "scope",
    "template_ref",
    "runtime_receipt_sha256",
    "environment_sha256",
    "parameter_set_sha256",
    "compiled_workflow_sha256",
    "phase",
    "run_index",
    "started_at",
    "completed_at",
    "peak_allocated_vram_bytes",
    "peak_reserved_vram_bytes",
    "wall_latency_ms",
    "oom",
    "partial_failure",
    "retry_count",
    "automatic_downgrade",
    "included_in_aggregate",
    "output_sha256",
    "automatic_metrics",
    "receipt_sha256",
}
_AUTOMATIC_METRIC_FIELDS = {
    "structural_similarity_bps",
    "product_fidelity_bps",
    "text_preservation_bps",
}
_ADMISSION_FIELDS = {
    "real_8gb_sample_admitted",
    "independent_human_review_completed",
    "rollback_exercised",
    "production_catalog_expansion_approved",
    "quality_score_used_as_human_review",
    "workflow_download_permitted",
}
_ZERO_FLAGS = {
    "content_asset_write": False,
    "formal_fact": False,
    "approval": False,
    "permit": False,
    "pilot": False,
    "outbox": False,
    "provider_call": False,
    "network": False,
    "external_write": False,
    "self_promotion": False,
    "production_template_admission": False,
}


class ComfyTemplateBenchmarkContractError(ValueError):
    pass


@dataclass(frozen=True)
class ComfyTemplateBenchmarkScope:
    tenant_ref: str
    entity_ref: str
    store_ref: str
    scope_grant_authority_sha256: str
    checked_at: datetime

    def projection(self) -> dict[str, str]:
        return {
            "tenant_ref": _token(self.tenant_ref, field="tenant_ref"),
            "entity_ref": _token(self.entity_ref, field="entity_ref"),
            "store_ref": _token(self.store_ref, field="store_ref"),
            "scope_grant_authority_sha256": _sha256(
                self.scope_grant_authority_sha256,
                field="scope_grant_authority_sha256",
            ),
        }


@dataclass(frozen=True)
class ComfyBenchmarkGateResult:
    gate_id: str
    status: str
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class ComfyTemplateBenchmarkObservation:
    observation_id: str
    contract_id: str
    template_ref: str
    fixture_ref: str
    evaluated_as_of: str
    scope_sha256: str
    registry_content_sha256: str
    fixture_content_sha256: str
    runtime_receipt_sha256: str | None
    run_receipt_sha256s: tuple[str, ...]
    compiled_workflow_sha256: str | None
    gate_results: tuple[ComfyBenchmarkGateResult, ...]
    blockers: tuple[str, ...]
    unknowns: tuple[str, ...]
    synthetic_contract_verified: bool
    candidate_state: str
    real_8gb_status: str
    production_admitted: bool
    media_qa_authority_ref: str
    required_media_qa_rules: tuple[str, ...]
    automatic_metric_summary: tuple[tuple[str, int], ...]
    side_effects: tuple[tuple[str, bool], ...]
    result_sha256: str

    def projection(self) -> dict[str, Any]:
        return asdict(self)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ComfyTemplateBenchmarkContractError("value is not canonical JSON") from exc


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _content_hash(value: Mapping[str, Any]) -> str:
    payload = dict(value)
    payload.pop("content_sha256", None)
    return _hash(payload)


def _receipt_hash(value: Mapping[str, Any]) -> str:
    payload = dict(value)
    payload.pop("receipt_sha256", None)
    return _hash(payload)


def _sha256(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise ComfyTemplateBenchmarkContractError(f"{field} must be a lowercase SHA-256")
    return value


def _token(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_TOKEN.fullmatch(value):
        raise ComfyTemplateBenchmarkContractError(f"{field} must be a safe token")
    return value


def _timestamp(value: Any, *, field: str) -> datetime:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ComfyTemplateBenchmarkContractError(f"{field} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ComfyTemplateBenchmarkContractError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _exact(value: Any, fields: set[str], *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ComfyTemplateBenchmarkContractError(f"{field} fields do not match contract")
    return value


def _strict_bool(value: Any, *, field: str) -> bool:
    if type(value) is not bool:
        raise ComfyTemplateBenchmarkContractError(f"{field} must be boolean")
    return value


def _integer(value: Any, *, field: str, minimum: int = 0, maximum: int = 2**63 - 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ComfyTemplateBenchmarkContractError(f"{field} is outside its integer bounds")
    return value


def _finite_number(value: Any, *, field: str, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ComfyTemplateBenchmarkContractError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise ComfyTemplateBenchmarkContractError(f"{field} must be finite and non-negative")
    return result


def _reject_sensitive(value: Any, *, path: str = "input") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            name = str(key).lower()
            if key != "contains_customer_data" and any(
                part in name for part in _SENSITIVE_KEY_PARTS
            ):
                raise ComfyTemplateBenchmarkContractError(f"{path} contains a sensitive field")
            _reject_sensitive(item, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _reject_sensitive(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str) and any(pattern.search(value) for pattern in _SECRET_PATTERNS):
        raise ComfyTemplateBenchmarkContractError(f"{path} contains sensitive content")


class GovernedComfyTemplateBenchmarkWorkspace:
    """Offline challenger benchmark; it never admits or executes a production workflow."""

    def __init__(
        self,
        *,
        scope: ComfyTemplateBenchmarkScope,
        repository_root: Path | None = None,
        _trusted_registry: Mapping[str, Any] | None = None,
        _trusted_fixture: Mapping[str, Any] | None = None,
    ) -> None:
        self.scope = scope
        root = repository_root or Path(__file__).resolve().parents[2]
        self.registry = (
            json.loads((root / REGISTRY_PATH).read_text(encoding="utf-8"))
            if _trusted_registry is None
            else json.loads(json.dumps(_trusted_registry))
        )
        self.fixture = (
            json.loads((root / FIXTURE_PATH).read_text(encoding="utf-8"))
            if _trusted_fixture is None
            else json.loads(json.dumps(_trusted_fixture))
        )
        self._test_seam = _trusted_registry is not None or _trusted_fixture is not None
        self._validate_registry()
        self._validate_fixture()

    @classmethod
    def from_trusted_documents_for_test(
        cls,
        *,
        scope: ComfyTemplateBenchmarkScope,
        registry: Mapping[str, Any],
        fixture: Mapping[str, Any],
    ) -> GovernedComfyTemplateBenchmarkWorkspace:
        return cls(scope=scope, _trusted_registry=registry, _trusted_fixture=fixture)

    def evaluate(
        self,
        template_ref: str,
        fixture_ref: str,
        runtime_receipt: Mapping[str, Any],
        run_receipts: Sequence[Mapping[str, Any]],
    ) -> ComfyTemplateBenchmarkObservation:
        template_ref = _token(template_ref, field="template_ref")
        fixture_ref = _token(fixture_ref, field="fixture_ref")
        if template_ref != self.fixture["template_ref"]:
            raise ComfyTemplateBenchmarkContractError("template_ref is not fixture-bound")
        if fixture_ref != self.fixture["fixture_ref"]:
            raise ComfyTemplateBenchmarkContractError("fixture_ref is not repository-owned")
        if (
            not isinstance(runtime_receipt, Mapping)
            or not isinstance(run_receipts, Sequence)
            or isinstance(run_receipts, (str, bytes, bytearray))
            or any(not isinstance(item, Mapping) for item in run_receipts)
        ):
            raise ComfyTemplateBenchmarkContractError("receipts do not match the contract")
        runtime = json.loads(json.dumps(runtime_receipt))
        runs = json.loads(json.dumps(list(run_receipts)))
        _reject_sensitive(runtime, path="runtime_receipt")
        _reject_sensitive(runs, path="run_receipts")

        gates: list[ComfyBenchmarkGateResult] = []
        blockers: set[str] = set()
        unknowns: set[str] = {
            "current_scope_authority",
            "current_runtime_authority",
            "independent_license_authority",
            "independent_run_authority",
            "real_8gb_peak_vram",
            "real_8gb_quality",
            "real_8gb_latency",
            "production_operating_cost",
        }
        runtime_sha: str | None = None
        run_shas: tuple[str, ...] = ()
        compiled_sha: str | None = None
        automatic_summary: tuple[tuple[str, int], ...] = ()

        def gate(gate_id: str, function: Any) -> Any:
            try:
                result = function()
            except ComfyTemplateBenchmarkContractError as exc:
                reason = _safe_reason(str(exc))
                blockers.add(reason)
                gates.append(ComfyBenchmarkGateResult(gate_id, "blocked", (reason,)))
                return None
            gates.append(ComfyBenchmarkGateResult(gate_id, "passed", ()))
            return result

        gate("registry_fixture_integrity", self._validate_document_bindings)
        scope_ready = gate("synthetic_scope_binding", lambda: self._validate_scope(runtime, runs))
        gate("current_scope_authority", self._block_current_scope_authority)
        compiled_sha = gate("typed_workflow_compiler", self._compile_fixture_workflow)
        runtime_sha = gate(
            "synthetic_runtime_receipt_shape",
            lambda: self._validate_runtime_after_scope(runtime, scope_ready),
        )
        gate("current_runtime_authority", self._block_current_runtime_authority)
        run_result = gate(
            "synthetic_run_receipt_shape",
            lambda: self._validate_runs(runtime, runs, compiled_sha, runtime_sha),
        )
        gate("independent_run_authority", self._block_independent_run_authority)
        if run_result is not None:
            run_shas, automatic_summary = run_result
        gate("synthetic_license_sbom_shape", lambda: self._validate_license(runtime, runtime_sha))
        gate("independent_license_authority", self._block_independent_license_authority)
        gate("media_qa_authority", self._validate_qa_authority)
        admission = self.fixture["admission_inputs"]
        gate(
            "real_8gb_sample",
            lambda: self._require_admission(
                admission,
                field="real_8gb_sample_admitted",
                reason="real_8gb_sample_missing",
            ),
        )
        gate(
            "independent_human_review",
            lambda: self._require_admission(
                admission,
                field="independent_human_review_completed",
                reason="independent_human_review_missing",
            ),
        )
        gate(
            "rollback",
            lambda: self._require_admission(
                admission,
                field="rollback_exercised",
                reason="rollback_not_exercised",
            ),
        )
        gate(
            "production_catalog_expansion",
            lambda: self._require_admission(
                admission,
                field="production_catalog_expansion_approved",
                reason="production_catalog_expansion_not_approved",
            ),
        )
        gate("production_admission_boundary", self._block_synthetic_slice)
        gate("zero_authority", self._validate_zero_authority)

        passed_contract = all(
            item.status == "passed"
            for item in gates
            if item.gate_id
            not in {
                "real_8gb_sample",
                "current_scope_authority",
                "current_runtime_authority",
                "independent_license_authority",
                "independent_run_authority",
                "independent_human_review",
                "rollback",
                "production_catalog_expansion",
                "production_admission_boundary",
            }
        )
        if not self.fixture["admission_inputs"]["real_8gb_sample_admitted"]:
            unknowns.add("real_8gb_sample")
        candidate_state = "not_admitted"
        payload = {
            "contract_id": OBSERVATION_CONTRACT_ID,
            "template_ref": template_ref,
            "fixture_ref": fixture_ref,
            "evaluated_as_of": self.scope.checked_at.astimezone(UTC).isoformat(),
            "scope_sha256": _hash(self.scope.projection()),
            "registry_content_sha256": self.registry["content_sha256"],
            "fixture_content_sha256": self.fixture["content_sha256"],
            "runtime_receipt_sha256": runtime_sha,
            "run_receipt_sha256s": list(run_shas),
            "compiled_workflow_sha256": compiled_sha,
            "gate_results": [asdict(item) for item in gates],
            "blockers": sorted(blockers),
            "unknowns": sorted(unknowns),
            "synthetic_contract_verified": passed_contract,
            "candidate_state": candidate_state,
            "real_8gb_status": "UNKNOWN",
            "production_admitted": False,
            "media_qa_authority_ref": self.registry["qa_authority"]["authority_ref"],
            "required_media_qa_rules": sorted(REQUIRED_QA | IMAGE_QA),
            "automatic_metric_summary": [list(item) for item in automatic_summary],
            "side_effects": sorted(_ZERO_FLAGS.items()),
        }
        result_sha = _hash(payload)
        observation_id = f"ctb_{result_sha[:24]}"
        return ComfyTemplateBenchmarkObservation(
            observation_id=observation_id,
            result_sha256=result_sha,
            **{**payload, "gate_results": tuple(gates), "blockers": tuple(sorted(blockers)),
               "unknowns": tuple(sorted(unknowns)), "run_receipt_sha256s": run_shas,
               "required_media_qa_rules": tuple(sorted(REQUIRED_QA | IMAGE_QA)),
               "automatic_metric_summary": automatic_summary,
               "side_effects": tuple(sorted(_ZERO_FLAGS.items()))},
        )

    def _validate_registry(self) -> None:
        registry = _exact(self.registry, _REGISTRY_FIELDS, field="registry")
        _sha256(registry["content_sha256"], field="registry.content_sha256")
        if _content_hash(registry) != registry["content_sha256"]:
            raise ComfyTemplateBenchmarkContractError("registry content hash drift")
        if not self._test_seam and registry["content_sha256"] != EXPECTED_REGISTRY_CONTENT_SHA256:
            raise ComfyTemplateBenchmarkContractError("registry is not the compiled trusted version")
        if registry["slice"] != "contract_synthetic_only":
            raise ComfyTemplateBenchmarkContractError("registry slice is not observation-only")
        truth = registry["production_truth"]
        if truth != {
            "template_catalog_ref": "apps.control_plane.media_workbench.TEMPLATE_CATALOG",
            "workflow_compiler_ref": "apps.control_plane.image_execution.ComfyImageExecutionService._workflow",
            "current_production_template_ref": "ozon-retouch-v1@1",
            "benchmark_registry_is_production_truth": False,
            "production_catalog_write_allowed": False,
        }:
            raise ComfyTemplateBenchmarkContractError("production truth boundary drift")
        champion = next((item for item in TEMPLATE_CATALOG if item["id"] == "ozon-retouch-v1"), None)
        if champion is None or champion.get("status") != "admitted" or champion.get("version") != "1":
            raise ComfyTemplateBenchmarkContractError("canonical production champion is unavailable")
        templates = registry["template_contracts"]
        if not isinstance(templates, list) or len(templates) != 1:
            raise ComfyTemplateBenchmarkContractError("registry requires exactly one shadow template")
        template = templates[0]
        if template.get("production_admitted") is not False or template.get("lifecycle") != "shadow_candidate":
            raise ComfyTemplateBenchmarkContractError("benchmark template cannot be production admitted")
        if template.get("workflow_download_allowed") is not False:
            raise ComfyTemplateBenchmarkContractError("workflow downloads are not admitted")
        workflow = template.get("workflow_contract")
        if not isinstance(workflow, dict) or _hash(workflow) != template.get("workflow_sha256"):
            raise ComfyTemplateBenchmarkContractError("workflow contract hash drift")
        if set(workflow) != {
            "contract_id",
            "nodes",
            "caller_workflow_json_allowed",
            "network_nodes_allowed",
            "custom_nodes_allowed",
        }:
            raise ComfyTemplateBenchmarkContractError("workflow contract fields drift")
        allowed = template.get("node_allowlist")
        classes = [node.get("class_type") for node in workflow.get("nodes", [])]
        if classes != allowed or any("custom" in str(item).lower() for item in classes):
            raise ComfyTemplateBenchmarkContractError("workflow contains an unadmitted node")
        if any("url" in str(key).lower() or "download" in str(key).lower() for key in _walk_keys(workflow)):
            raise ComfyTemplateBenchmarkContractError("workflow contains a download field")
        if registry["hard_gate_ids"] != [
            "registry_fixture_integrity",
            "synthetic_scope_binding",
            "current_scope_authority",
            "typed_workflow_compiler",
            "synthetic_runtime_receipt_shape",
            "current_runtime_authority",
            "synthetic_run_receipt_shape",
            "independent_run_authority",
            "synthetic_license_sbom_shape",
            "independent_license_authority",
            "media_qa_authority",
            "real_8gb_sample",
            "independent_human_review",
            "rollback",
            "production_catalog_expansion",
            "production_admission_boundary",
            "zero_authority",
        ]:
            raise ComfyTemplateBenchmarkContractError("hard Gate registry drift")

    def _validate_fixture(self) -> None:
        fixture = _exact(self.fixture, _FIXTURE_FIELDS, field="fixture")
        _sha256(fixture["content_sha256"], field="fixture.content_sha256")
        if _content_hash(fixture) != fixture["content_sha256"]:
            raise ComfyTemplateBenchmarkContractError("fixture content hash drift")
        if not self._test_seam and fixture["content_sha256"] != EXPECTED_FIXTURE_CONTENT_SHA256:
            raise ComfyTemplateBenchmarkContractError("fixture is not the compiled trusted version")
        if fixture["registry_content_sha256"] != self.registry["content_sha256"]:
            raise ComfyTemplateBenchmarkContractError("fixture registry binding drift")
        if fixture["contains_customer_data"] is not False or fixture["contains_secrets"] is not False:
            raise ComfyTemplateBenchmarkContractError("fixture is not synthetic and minimized")
        _exact(fixture["scope"], _SCOPE_FIELDS, field="fixture.scope")
        _exact(fixture["admission_inputs"], _ADMISSION_FIELDS, field="admission_inputs")

    def _validate_document_bindings(self) -> None:
        if self.fixture["expected"] != {
            "synthetic_contract_verified": True,
            "candidate_state": "not_admitted",
            "real_8gb_status": "UNKNOWN",
            "production_admitted": False,
        }:
            raise ComfyTemplateBenchmarkContractError("fixture expected outcome drift")

    def _validate_scope(self, runtime: dict[str, Any], runs: list[dict[str, Any]]) -> bool:
        expected = self.scope.projection()
        if self.fixture["scope"] != expected:
            raise ComfyTemplateBenchmarkContractError("exact scope fixture binding mismatch")
        checked_at = _timestamp(self.scope.checked_at, field="scope.checked_at")
        if _timestamp(self.fixture["data_as_of"], field="data_as_of") > checked_at:
            raise ComfyTemplateBenchmarkContractError("data_as_of is after trusted current time")
        if runtime.get("scope") != expected or any(item.get("scope") != expected for item in runs):
            raise ComfyTemplateBenchmarkContractError("receipt exact scope or authority drift")
        return True

    def _validate_runtime_after_scope(
        self,
        runtime: dict[str, Any],
        scope_ready: bool | None,
    ) -> str:
        if scope_ready is not True:
            raise ComfyTemplateBenchmarkContractError("synthetic scope binding is unavailable")
        return self._validate_runtime(runtime)

    def _template(self) -> dict[str, Any]:
        return next(
            item for item in self.registry["template_contracts"]
            if item["template_ref"] == self.fixture["template_ref"]
        )

    def _compile_fixture_workflow(self) -> str:
        template = self._template()
        parameters = self.fixture["parameter_set"]
        schema = template["typed_parameters"]
        if not isinstance(parameters, dict) or set(parameters) != set(schema):
            raise ComfyTemplateBenchmarkContractError("typed parameter set mismatch")
        for name, contract in schema.items():
            value = parameters[name]
            kind = contract["type"]
            if kind == "string":
                _token(value, field=name)
            elif kind == "integer":
                _integer(value, field=name, minimum=contract["minimum"], maximum=contract["maximum"])
            elif kind == "number":
                numeric = _finite_number(value, field=name, minimum=float(contract["minimum"]))
                if numeric > float(contract["maximum"]):
                    raise ComfyTemplateBenchmarkContractError(f"{name} exceeds its maximum")
            elif kind == "enum":
                if value not in contract["values"]:
                    raise ComfyTemplateBenchmarkContractError(f"{name} is not admitted")
            else:
                raise ComfyTemplateBenchmarkContractError("unknown parameter type")
        workflow = {
            "1": {"class_type": "LoadImage", "inputs": {"image": parameters["input_image_ref"]}},
            "2": {
                "class_type": "ImageScaleToTotalPixels",
                "inputs": {
                    "image": ["1", 0],
                    "upscale_method": parameters["upscale_method"],
                    "megapixels": parameters["target_megapixels"],
                    "resolution_steps": 1,
                },
            },
            "3": {
                "class_type": "SaveImage",
                "inputs": {
                    "images": ["2", 0],
                    "filename_prefix": "synthetic/bas185/output",
                },
            },
        }
        if {node["class_type"] for node in workflow.values()} != set(template["node_allowlist"]):
            raise ComfyTemplateBenchmarkContractError("compiled workflow node allowlist drift")
        compiled = _hash(workflow)
        if compiled != self.fixture["compiled_workflow_sha256"]:
            raise ComfyTemplateBenchmarkContractError("compiled workflow hash drift")
        return compiled

    def _validate_runtime(self, runtime: dict[str, Any]) -> str:
        runtime = _exact(runtime, _RUNTIME_FIELDS, field="runtime_receipt")
        actual_sha = _receipt_hash(runtime)
        if runtime["receipt_sha256"] != actual_sha:
            raise ComfyTemplateBenchmarkContractError("runtime receipt hash drift")
        if runtime != self.fixture["runtime_receipt"]:
            raise ComfyTemplateBenchmarkContractError("runtime receipt is not fixture-authorized")
        recorded = _timestamp(runtime["recorded_at"], field="runtime.recorded_at")
        effective = _timestamp(runtime["effective_at"], field="runtime.effective_at")
        until = _timestamp(runtime["effective_until"], field="runtime.effective_until")
        checked = _timestamp(self.scope.checked_at, field="scope.checked_at")
        if not effective <= recorded <= checked < until:
            raise ComfyTemplateBenchmarkContractError("runtime receipt is stale or future-dated")
        environment = _exact(runtime["environment"], _ENVIRONMENT_FIELDS, field="environment")
        if environment["total_vram_bytes"] != 8 * GIB:
            raise ComfyTemplateBenchmarkContractError("runtime is not the fixed 8GB profile")
        for field in (
            "model_sha256",
            "node_bundle_sha256",
            "node_registry_sha256",
            "environment_sha256",
            "sbom_sha256",
        ):
            target = runtime if field == "sbom_sha256" else environment
            _sha256(target[field], field=field)
        computed_env = _hash({key: value for key, value in environment.items() if key != "environment_sha256"})
        if computed_env != environment["environment_sha256"]:
            raise ComfyTemplateBenchmarkContractError("runtime environment digest drift")
        template = self._template()
        model_policy = template["model_policy"]
        node_policy = template["node_bundle_policy"]
        if (
            environment["model_artifact_id"] != model_policy["artifact_id"]
            or environment["model_sha256"] != model_policy["artifact_sha256"]
        ):
            raise ComfyTemplateBenchmarkContractError("runtime model provenance drift")
        if (
            environment["node_bundle_id"] != node_policy["bundle_id"]
            or environment["node_bundle_sha256"] != node_policy["bundle_sha256"]
        ):
            raise ComfyTemplateBenchmarkContractError("runtime node bundle provenance drift")
        workload = _exact(runtime["workload"], _WORKLOAD_FIELDS, field="workload")
        policy = self.registry["benchmark_policy"]
        for field in ("resolution_width", "resolution_height", "batch_size", "seed", "warmup_runs", "measurement_runs"):
            _integer(workload[field], field=f"workload.{field}")
        if workload != policy["fixed_workload"]:
            raise ComfyTemplateBenchmarkContractError("runtime workload is not the frozen profile")
        return actual_sha

    def _validate_runs(
        self,
        runtime: dict[str, Any],
        runs: list[dict[str, Any]],
        compiled_sha: str | None,
        runtime_sha: str | None,
    ) -> tuple[tuple[str, ...], tuple[tuple[str, int], ...]]:
        if compiled_sha is None:
            raise ComfyTemplateBenchmarkContractError("compiled workflow unavailable")
        if runtime_sha is None:
            raise ComfyTemplateBenchmarkContractError("runtime receipt unavailable")
        workload = runtime["workload"]
        expected_count = workload["warmup_runs"] + workload["measurement_runs"]
        if len(runs) != expected_count or runs != self.fixture["run_receipts"]:
            raise ComfyTemplateBenchmarkContractError("run set is incomplete or cherry-picked")
        if runtime_sha != runtime["receipt_sha256"]:
            raise ComfyTemplateBenchmarkContractError("runtime receipt binding unavailable")
        parameter_sha = _hash(self.fixture["parameter_set"])
        environment_sha = runtime["environment"]["environment_sha256"]
        total_vram = runtime["environment"]["total_vram_bytes"]
        policy = self.registry["benchmark_policy"]
        seen: set[tuple[str, int]] = set()
        receipt_shas: list[str] = []
        measurements: list[dict[str, Any]] = []
        for run in runs:
            run = _exact(run, _RUN_FIELDS, field="run_receipt")
            actual_sha = _receipt_hash(run)
            if actual_sha != run["receipt_sha256"]:
                raise ComfyTemplateBenchmarkContractError("run receipt hash drift")
            receipt_shas.append(actual_sha)
            phase = run["phase"]
            if phase not in {"warmup", "measurement"}:
                raise ComfyTemplateBenchmarkContractError("run phase is invalid")
            index = _integer(run["run_index"], field="run_index")
            if (phase, index) in seen:
                raise ComfyTemplateBenchmarkContractError("duplicate run index")
            seen.add((phase, index))
            if run["runtime_receipt_sha256"] != runtime_sha or run["environment_sha256"] != environment_sha:
                raise ComfyTemplateBenchmarkContractError("run runtime binding drift")
            if run["parameter_set_sha256"] != parameter_sha or run["compiled_workflow_sha256"] != compiled_sha:
                raise ComfyTemplateBenchmarkContractError("run workflow or parameter binding drift")
            started = _timestamp(run["started_at"], field="run.started_at")
            completed = _timestamp(run["completed_at"], field="run.completed_at")
            if completed < started or completed > self.scope.checked_at.astimezone(UTC):
                raise ComfyTemplateBenchmarkContractError("run timestamps are invalid")
            allocated = _integer(run["peak_allocated_vram_bytes"], field="peak_allocated_vram_bytes")
            reserved = _integer(run["peak_reserved_vram_bytes"], field="peak_reserved_vram_bytes")
            latency = _finite_number(run["wall_latency_ms"], field="wall_latency_ms")
            if allocated > reserved or reserved > total_vram or reserved > policy["maximum_peak_reserved_vram_bytes"]:
                raise ComfyTemplateBenchmarkContractError("run exceeds the 8GB memory envelope")
            if latency > policy["maximum_wall_latency_ms"]:
                raise ComfyTemplateBenchmarkContractError("run latency exceeds the fixed threshold")
            if run["oom"] is not False or run["partial_failure"] is not False:
                raise ComfyTemplateBenchmarkContractError("OOM or partial output cannot pass")
            if run["retry_count"] != 0 or run["automatic_downgrade"] is not False:
                raise ComfyTemplateBenchmarkContractError("automatic retry or downgrade is not admitted")
            _sha256(run["output_sha256"], field="output_sha256")
            metrics = _exact(run["automatic_metrics"], _AUTOMATIC_METRIC_FIELDS, field="automatic_metrics")
            for metric, value in metrics.items():
                score = _integer(value, field=metric, maximum=10_000)
                if score < policy["automatic_metric_floors_bps"][metric]:
                    raise ComfyTemplateBenchmarkContractError("automatic quality observation is below floor")
            expected_inclusion = phase == "measurement"
            if run["included_in_aggregate"] is not expected_inclusion:
                raise ComfyTemplateBenchmarkContractError("run sample selection is incomplete")
            if phase == "measurement":
                measurements.append(run)
        expected_indexes = {
            *(('warmup', index) for index in range(workload["warmup_runs"])),
            *(('measurement', index) for index in range(workload["measurement_runs"])),
        }
        if seen != expected_indexes or len(measurements) != workload["measurement_runs"]:
            raise ComfyTemplateBenchmarkContractError("warmup or repeat contract is incomplete")
        summary = tuple(
            sorted(
                (
                    metric,
                    int(mean(run["automatic_metrics"][metric] for run in measurements)),
                )
                for metric in _AUTOMATIC_METRIC_FIELDS
            )
        )
        return tuple(receipt_shas), summary

    def _validate_license(self, runtime: dict[str, Any], runtime_sha: str | None) -> None:
        if runtime_sha is None:
            raise ComfyTemplateBenchmarkContractError("runtime receipt unavailable")
        license_receipt = _exact(runtime["license_attestation"], _LICENSE_FIELDS, field="license_attestation")
        template = self._template()
        expected = template["license_policy"]
        if license_receipt["model_license_id"] != expected["model_license_id"]:
            raise ComfyTemplateBenchmarkContractError("model license is incompatible")
        if license_receipt["node_bundle_license_id"] != expected["node_bundle_license_id"]:
            raise ComfyTemplateBenchmarkContractError("node bundle license is incompatible")
        if license_receipt["commercial_use_allowed"] is not True or license_receipt["redistribution_reviewed"] is not True:
            raise ComfyTemplateBenchmarkContractError("license attestation is incomplete")
        attestation_sha256 = _hash(
            {
                key: value
                for key, value in license_receipt.items()
                if key != "attestation_sha256"
            }
        )
        if license_receipt["attestation_sha256"] != attestation_sha256:
            raise ComfyTemplateBenchmarkContractError("synthetic license attestation hash drift")
        if runtime["sbom_sha256"] != template["sbom_sha256"]:
            raise ComfyTemplateBenchmarkContractError("SBOM binding drift")

    def _validate_qa_authority(self) -> None:
        qa = self.registry["qa_authority"]
        expected = sorted(REQUIRED_QA | IMAGE_QA)
        if qa != {
            "authority_ref": "apps.control_plane.content_growth.REQUIRED_QA+IMAGE_QA",
            "required_rules": expected,
            "automatic_metrics_are_observations_only": True,
            "independent_human_review_required": True,
        }:
            raise ComfyTemplateBenchmarkContractError("Media QA authority drift")
        admission = self.fixture["admission_inputs"]
        _exact(admission, _ADMISSION_FIELDS, field="admission_inputs")
        if admission["quality_score_used_as_human_review"] is not False:
            raise ComfyTemplateBenchmarkContractError("automatic quality cannot replace human review")
        if admission["workflow_download_permitted"] is not False:
            raise ComfyTemplateBenchmarkContractError("workflow or model download is prohibited")

    @staticmethod
    def _require_admission(
        admission: Mapping[str, Any],
        *,
        field: str,
        reason: str,
    ) -> None:
        if admission[field] is not True:
            raise ComfyTemplateBenchmarkContractError(reason)

    def _validate_zero_authority(self) -> None:
        if self.registry["zero_authority_flags"] != _ZERO_FLAGS:
            raise ComfyTemplateBenchmarkContractError("zero-authority boundary drift")

    @staticmethod
    def _block_synthetic_slice() -> None:
        raise ComfyTemplateBenchmarkContractError(
            "synthetic_contract_slice_not_production_evidence"
        )

    @staticmethod
    def _block_current_scope_authority() -> None:
        raise ComfyTemplateBenchmarkContractError(
            "current_scope_authority_not_connected_in_synthetic_slice"
        )

    @staticmethod
    def _block_current_runtime_authority() -> None:
        raise ComfyTemplateBenchmarkContractError(
            "current_runtime_authority_not_connected_in_synthetic_slice"
        )

    @staticmethod
    def _block_independent_run_authority() -> None:
        raise ComfyTemplateBenchmarkContractError(
            "independent_run_authority_not_connected_in_synthetic_slice"
        )

    @staticmethod
    def _block_independent_license_authority() -> None:
        raise ComfyTemplateBenchmarkContractError(
            "independent_license_authority_not_connected_in_synthetic_slice"
        )


def _safe_reason(reason: str) -> str:
    parts = [part.strip() for part in reason.split(";") if part.strip()]
    if len(parts) > 1:
        return "+".join(sorted(_safe_reason(part) for part in parts))
    normalized = re.sub(r"[^a-z0-9]+", "_", reason.lower()).strip("_")
    return normalized[:120] or "benchmark_contract_invalid"


def _walk_keys(value: Any) -> list[str]:
    keys: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            keys.append(str(key))
            keys.extend(_walk_keys(item))
    elif isinstance(value, list):
        for item in value:
            keys.extend(_walk_keys(item))
    return keys

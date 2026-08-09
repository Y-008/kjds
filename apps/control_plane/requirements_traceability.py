from __future__ import annotations

import hashlib
import json
import os
import re
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any


class RequirementsTraceabilityError(ValueError):
    """Raised when the historical-requirement contract is unsafe or drifts."""


class RequirementsTraceabilityProgram:
    """Compile historical requests into a read-only traceability projection.

    Construction reads and validates the static registry once. ``project`` is
    deliberately a zero-argument Interface and performs no I/O. The registry is
    not an authority for people, work, business outcomes, gates or execution.
    """

    CONTRACT_ID = "kjds-requirements-traceability-program-v1"
    SCHEMA_VERSION = "kjds-requirements-traceability-v1"
    SUPPORTED_VERSION = "1.0.0"
    STATUS_VOCABULARY = (
        "ADOPTED_ENGINEERING",
        "ISOLATED_IMPLEMENTED",
        "CONTRACT_ONLY",
        "PILOT_PENDING",
        "BLOCKED_EVIDENCE",
        "REJECTED_DUPLICATE",
    )
    AUTOMATION_CONTRACT_REFS = (
        "automation_grant_authority_v1",
        "automation_safety_case_v1",
        "process_conformance_report_v1",
        "automation_value_ledger_v1",
        "automation_capability_passport_v1",
    )
    ENTRY_FIELDS = frozenset(
        {
            "trace_ref",
            "title",
            "requirement_sources",
            "requirement_ids",
            "machine_contract_refs",
            "implementation_paths",
            "current_version",
            "owner",
            "gate_refs",
            "evidence_refs",
            "status",
            "unfinished_items",
            "business_truth_status",
            "business_truth_proven",
        }
    )
    OPTIONAL_ENTRY_FIELDS = frozenset(
        {
            "pilot",
            "blocking_evidence_refs",
            "canonical_owner_ref",
            "rejection_reason",
        }
    )
    CURRENT_VERSION_FIELDS = frozenset({"kind", "ref", "reviewed_on"})
    ISOLATED_VERSION_FIELDS = frozenset(
        {"branch", "head", "mainline_integration_status"}
    )
    VERSION_KINDS_BY_STATUS = {
        "ADOPTED_ENGINEERING": frozenset(
            {"contract", "document_contract", "engineering_commit", "engineering_contract"}
        ),
        "ISOLATED_IMPLEMENTED": frozenset({"isolated_git_head"}),
        "CONTRACT_ONLY": frozenset({"contract"}),
        "PILOT_PENDING": frozenset({"decision_contract"}),
        "BLOCKED_EVIDENCE": frozenset({"evidence_gap_contract"}),
        "REJECTED_DUPLICATE": frozenset({"architecture_decision"}),
    }
    FORBIDDEN_DYNAMIC_TRUTH_FIELDS = frozenset(
        {
            "actual_result",
            "realized_value",
            "gate_passed",
            "human_bound",
            "production_ready",
            "top1_claim",
            "runtime_execution_enabled",
            "grant_ready",
            "current_task",
            "active_writer_ref",
        }
    )
    _IDENTIFIER = re.compile(r"[A-Za-z0-9_.:/@+-]+")
    _SHA256 = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
    _DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

    def __init__(self, registry_path: str | Path | None = None) -> None:
        self.root = Path(__file__).resolve().parents[2]
        configured = registry_path or os.getenv(
            "KJDS_REQUIREMENTS_TRACEABILITY_REGISTRY_PATH"
        )
        self.registry_path = (
            Path(configured)
            if configured
            else self.root
            / "docs"
            / "project"
            / "registries"
            / "requirements_traceability.json"
        )
        try:
            raw = self.registry_path.read_bytes()
            registry = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RequirementsTraceabilityError(
                "Requirements traceability registry is unreadable"
            ) from exc
        if not isinstance(registry, dict):
            raise RequirementsTraceabilityError(
                "Requirements traceability registry must be an object"
            )

        self._validate_registry(registry)
        self.registry_sha256 = hashlib.sha256(raw).hexdigest()
        self._registry = deepcopy(registry)
        self._projection = self._compile_projection()

    def project(self) -> dict[str, Any]:
        """Return a defensive copy of the compiled structural contract."""

        return deepcopy(self._projection)

    @staticmethod
    def _canonical_hash(value: Any) -> str:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _require_string(value: Any, label: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise RequirementsTraceabilityError(f"{label} must be a non-empty string")
        return value.strip()

    @classmethod
    def _require_string_list(cls, value: Any, label: str) -> list[str]:
        if not isinstance(value, list) or not value:
            raise RequirementsTraceabilityError(f"{label} must be a non-empty list")
        result = [cls._require_string(item, f"{label} item") for item in value]
        if len(result) != len(set(result)):
            raise RequirementsTraceabilityError(f"{label} values must be unique")
        return result

    @classmethod
    def _reject_dynamic_truth_fields(cls, value: Any, path: str = "registry") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in cls.FORBIDDEN_DYNAMIC_TRUTH_FIELDS:
                    raise RequirementsTraceabilityError(
                        f"{path}.{key} is forbidden dynamic truth"
                    )
                cls._reject_dynamic_truth_fields(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                cls._reject_dynamic_truth_fields(item, f"{path}[{index}]")

    def _validate_registry(self, registry: dict[str, Any]) -> None:
        required = {
            "schema_version",
            "contract_id",
            "version",
            "as_of",
            "status_vocabulary",
            "truth_boundary",
            "automation_control_contracts",
            "traceability_entries",
        }
        if set(registry) != required:
            raise RequirementsTraceabilityError(
                "Requirements traceability root fields drifted"
            )
        if registry["schema_version"] != self.SCHEMA_VERSION:
            raise RequirementsTraceabilityError("Unsupported traceability schema")
        if registry["contract_id"] != self.CONTRACT_ID:
            raise RequirementsTraceabilityError("Traceability contract id drifted")
        if registry["version"] != self.SUPPORTED_VERSION:
            raise RequirementsTraceabilityError("Unsupported traceability version")
        if not self._DATE.fullmatch(self._require_string(registry["as_of"], "as_of")):
            raise RequirementsTraceabilityError("as_of must use YYYY-MM-DD")
        if tuple(registry["status_vocabulary"]) != self.STATUS_VOCABULARY:
            raise RequirementsTraceabilityError("Status vocabulary drifted")

        self._reject_dynamic_truth_fields(registry)
        self._validate_truth_boundary(registry["truth_boundary"])
        self._validate_automation_contracts(registry["automation_control_contracts"])
        self._validate_entries(registry["traceability_entries"])

    @staticmethod
    def _validate_truth_boundary(boundary: Any) -> None:
        expected = {
            "static_registry_is_business_authority",
            "engineering_status_proves_business_result",
            "isolated_implementation_is_mainline_integration",
            "contract_status_grants_runtime_execution",
            "status_can_create_fact",
            "status_can_create_finance_entry",
            "status_can_create_approval",
            "status_can_create_permit",
            "status_can_enable_external_write",
        }
        if not isinstance(boundary, dict) or set(boundary) != expected:
            raise RequirementsTraceabilityError("Truth boundary fields drifted")
        if any(value is not False for value in boundary.values()):
            raise RequirementsTraceabilityError("Static traceability must grant no authority")

    def _validate_automation_contracts(self, contracts: Any) -> None:
        if not isinstance(contracts, list) or len(contracts) != 5:
            raise RequirementsTraceabilityError(
                "Exactly five automation control contracts are required"
            )
        refs: list[str] = []
        expected_fields = {
            "contract_ref",
            "title",
            "status",
            "owner_role_ref",
            "required_fields",
            "lifecycle",
            "gate_refs",
            "runtime_connected",
            "creates_authority",
            "external_write_allowed",
        }
        for index, contract in enumerate(contracts):
            if not isinstance(contract, dict) or set(contract) != expected_fields:
                raise RequirementsTraceabilityError(
                    f"automation contract {index} fields drifted"
                )
            ref = self._require_string(contract["contract_ref"], "contract_ref")
            refs.append(ref)
            self._require_string(contract["title"], f"{ref}.title")
            self._require_string(contract["owner_role_ref"], f"{ref}.owner")
            self._require_string_list(contract["required_fields"], f"{ref}.required_fields")
            self._require_string_list(contract["lifecycle"], f"{ref}.lifecycle")
            self._require_string_list(contract["gate_refs"], f"{ref}.gate_refs")
            if contract["status"] != "CONTRACT_ONLY":
                raise RequirementsTraceabilityError(
                    f"{ref} must remain CONTRACT_ONLY in BAS-218"
                )
            for key in (
                "runtime_connected",
                "creates_authority",
                "external_write_allowed",
            ):
                if contract[key] is not False:
                    raise RequirementsTraceabilityError(f"{ref}.{key} must be false")
        if tuple(refs) != self.AUTOMATION_CONTRACT_REFS:
            raise RequirementsTraceabilityError("Automation contract set drifted")

    def _validate_entries(self, entries: Any) -> None:
        if not isinstance(entries, list) or len(entries) < 10:
            raise RequirementsTraceabilityError(
                "At least ten historical traceability entries are required"
            )
        refs: list[str] = []
        observed_statuses: set[str] = set()
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise RequirementsTraceabilityError(f"trace entry {index} must be an object")
            keys = set(entry)
            if not self.ENTRY_FIELDS.issubset(keys):
                raise RequirementsTraceabilityError(
                    f"trace entry {index} is missing required fields"
                )
            if keys - self.ENTRY_FIELDS - self.OPTIONAL_ENTRY_FIELDS:
                raise RequirementsTraceabilityError(
                    f"trace entry {index} contains unknown fields"
                )
            ref = self._require_string(entry["trace_ref"], "trace_ref")
            if not self._IDENTIFIER.fullmatch(ref):
                raise RequirementsTraceabilityError(f"Invalid trace ref {ref}")
            refs.append(ref)
            self._require_string(entry["title"], f"{ref}.title")
            for key in (
                "requirement_sources",
                "requirement_ids",
                "machine_contract_refs",
                "implementation_paths",
                "gate_refs",
                "evidence_refs",
                "unfinished_items",
            ):
                self._require_string_list(entry[key], f"{ref}.{key}")

            status = self._require_string(entry["status"], f"{ref}.status")
            if status not in self.STATUS_VOCABULARY:
                raise RequirementsTraceabilityError(f"Unsupported status {status}")
            observed_statuses.add(status)
            if entry["business_truth_status"] != "UNKNOWN":
                raise RequirementsTraceabilityError(
                    f"{ref} may not claim a business truth status"
                )
            if entry["business_truth_proven"] is not False:
                raise RequirementsTraceabilityError(
                    f"{ref} may not prove a business outcome"
                )
            self._validate_owner(ref, entry["owner"])
            self._validate_current_version(ref, status, entry["current_version"])
            self._validate_paths(ref, status, entry["implementation_paths"])
            self._validate_paths(ref, status, entry["evidence_refs"])
            self._validate_status_specific(ref, status, entry)

        if len(refs) != len(set(refs)):
            raise RequirementsTraceabilityError("Trace refs must be unique")
        if observed_statuses != set(self.STATUS_VOCABULARY):
            raise RequirementsTraceabilityError(
                "Every traceability status must be represented"
            )

    def _validate_owner(self, ref: str, owner: Any) -> None:
        if not isinstance(owner, dict) or set(owner) != {
            "role_ref",
            "alternate_role_ref",
        }:
            raise RequirementsTraceabilityError(f"{ref}.owner fields drifted")
        primary = self._require_string(owner["role_ref"], f"{ref}.owner.role_ref")
        alternate = self._require_string(
            owner["alternate_role_ref"], f"{ref}.owner.alternate_role_ref"
        )
        if primary == alternate:
            raise RequirementsTraceabilityError(f"{ref} owner and alternate must differ")

    def _validate_current_version(self, ref: str, status: str, version: Any) -> None:
        if not isinstance(version, dict):
            raise RequirementsTraceabilityError(f"{ref}.current_version must be an object")
        expected = set(self.CURRENT_VERSION_FIELDS)
        if status == "ISOLATED_IMPLEMENTED":
            expected |= set(self.ISOLATED_VERSION_FIELDS)
        if set(version) != expected:
            raise RequirementsTraceabilityError(f"{ref}.current_version fields drifted")
        for key in self.CURRENT_VERSION_FIELDS:
            self._require_string(version[key], f"{ref}.current_version.{key}")
        if not self._DATE.fullmatch(version["reviewed_on"]):
            raise RequirementsTraceabilityError(f"{ref}.reviewed_on must use YYYY-MM-DD")
        if status == "ISOLATED_IMPLEMENTED":
            self._require_string(version["branch"], f"{ref}.branch")
            head = self._require_string(version["head"], f"{ref}.head")
            if not self._SHA256.fullmatch(head):
                raise RequirementsTraceabilityError(f"{ref}.head must be a git hash")
            if version["ref"] != head:
                raise RequirementsTraceabilityError(f"{ref}.ref and head must match")
            if version["mainline_integration_status"] != "NOT_STARTED":
                raise RequirementsTraceabilityError(
                    f"{ref} cannot claim mainline integration"
                )

    def _validate_paths(self, ref: str, status: str, paths: list[str]) -> None:
        for value in paths:
            if value.startswith("isolated:"):
                if status != "ISOLATED_IMPLEMENTED":
                    raise RequirementsTraceabilityError(
                        f"{ref} uses isolated path without isolated status"
                    )
                relative = value.removeprefix("isolated:")
                self._validate_relative_path(ref, relative)
                continue
            self._validate_relative_path(ref, value)
            if not (self.root / value).is_file():
                raise RequirementsTraceabilityError(
                    f"{ref} references missing repository file {value}"
                )

    @staticmethod
    def _validate_relative_path(ref: str, value: str) -> None:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise RequirementsTraceabilityError(f"{ref} contains unsafe path {value}")

    def _validate_status_specific(
        self, ref: str, status: str, entry: dict[str, Any]
    ) -> None:
        version_kind = entry["current_version"]["kind"]
        if version_kind not in self.VERSION_KINDS_BY_STATUS[status]:
            raise RequirementsTraceabilityError(
                f"{ref} version kind is incompatible with status {status}"
            )
        expected_optional_fields: set[str] = set()
        if status == "ISOLATED_IMPLEMENTED":
            if "selective_mainline_integration_gate" not in entry["gate_refs"]:
                raise RequirementsTraceabilityError(
                    f"{ref} lacks selective mainline integration gate"
                )
            if not all(path.startswith("isolated:") for path in entry["implementation_paths"]):
                raise RequirementsTraceabilityError(
                    f"{ref} isolated implementation paths must stay isolated"
                )
        elif status == "PILOT_PENDING":
            expected_optional_fields = {"pilot"}
            pilot = entry.get("pilot")
            if not isinstance(pilot, dict) or set(pilot) != {
                "entry_gate_refs",
                "exit_gate_refs",
            }:
                raise RequirementsTraceabilityError(f"{ref} lacks pilot gate contract")
            self._require_string_list(pilot["entry_gate_refs"], f"{ref}.pilot.entry")
            self._require_string_list(pilot["exit_gate_refs"], f"{ref}.pilot.exit")
        elif status == "BLOCKED_EVIDENCE":
            expected_optional_fields = {"blocking_evidence_refs"}
            self._require_string_list(
                entry.get("blocking_evidence_refs"), f"{ref}.blocking_evidence_refs"
            )
        elif status == "REJECTED_DUPLICATE":
            expected_optional_fields = {"canonical_owner_ref", "rejection_reason"}
            self._require_string(entry.get("canonical_owner_ref"), f"{ref}.canonical_owner_ref")
            self._require_string(entry.get("rejection_reason"), f"{ref}.rejection_reason")
        observed_optional_fields = set(entry) & set(self.OPTIONAL_ENTRY_FIELDS)
        if observed_optional_fields != expected_optional_fields:
            raise RequirementsTraceabilityError(
                f"{ref} optional fields are incompatible with status {status}"
            )

    def _compile_projection(self) -> dict[str, Any]:
        entries = deepcopy(self._registry["traceability_entries"])
        counts = {status: 0 for status in self.STATUS_VOCABULARY}
        for entry in entries:
            counts[entry["status"]] += 1
        basis = {
            "contract_id": self.CONTRACT_ID,
            "schema_version": self.SCHEMA_VERSION,
            "version": self.SUPPORTED_VERSION,
            "as_of": self._registry["as_of"],
            "registry_sha256": self.registry_sha256,
            "contract_integrity": {
                "status": "VERIFIED",
                "reason_codes": ["static_registry_schema_and_references_verified"],
            },
            "status_vocabulary": list(self.STATUS_VOCABULARY),
            "counts": {"total": len(entries), "by_status": counts},
            "traceability_entries": entries,
            "automation_control_contracts": deepcopy(
                self._registry["automation_control_contracts"]
            ),
            "dynamic_truth": {
                "status": "UNKNOWN",
                "human_bindings": None,
                "real_sku_cash_loop": None,
                "real_rfq_and_quotes": None,
                "customer_value": None,
                "production_gate": None,
                "top1_claim": False,
                "reason_codes": ["runtime_business_authorities_not_connected"],
            },
            "control_envelope": {
                "read_only": True,
                "static_registry_is_business_authority": False,
                "operating_task_created": False,
                "fact_created": False,
                "finance_entry_created": False,
                "approval_created": False,
                "permit_created": False,
                "external_write_allowed": False,
            },
        }
        return {**basis, "snapshot_sha256": self._canonical_hash(basis)}

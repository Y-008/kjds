from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

ATLAS_STATUSES = ("implemented", "ready", "gated", "research_only")
REQUIRED_CAPABILITY_FIELDS = (
    "id",
    "label",
    "summary",
    "linkfox",
    "surpass",
    "russia",
    "global",
    "technology",
    "inputs",
    "outputs",
    "status",
    "markets",
    "platforms",
    "controls",
    "workspace",
)
REQUIRED_POINT_FIELDS = (
    "id",
    "label",
    "domain_id",
    "parent_capability_id",
    "objective",
    "business_object",
    "operation_kind",
    "contract_profile_id",
    "source_kind",
    "evidence_tier",
    "source_boundary",
    "status",
    "input_contract",
    "output_contract",
    "technology",
    "evidence_gate",
    "failure_modes",
    "failure_queue",
    "readback",
    "kpi",
    "sla",
    "owner",
    "reviewer",
    "markets",
    "platforms",
    "controls",
    "value_stream_ids",
    "workspace",
)
REQUIRED_STREAM_FIELDS = (
    "id",
    "label",
    "mission",
    "stage_point_ids",
    "supporting_point_ids",
    "object_transitions",
    "entry_gate",
    "exit_gate",
    "events",
    "exceptions",
    "human_takeover",
    "kpi",
    "sla",
    "adapter_boundary",
)
REQUIRED_SURFACE_FIELDS = (
    "id",
    "label",
    "mission",
    "value_stream_ids",
    "focus_point_ids",
    "dimensions",
    "decisions",
    "truth_owner",
    "kpi",
    "alerts",
    "write_boundary",
)


class CapabilityAtlasError(ValueError):
    """Raised when the versioned capability atlas is structurally unsafe."""


class CrossBorderCapabilityAtlas:
    """Validate and project the Russia-first cross-border capability tree.

    The registry is product architecture, not a runtime capability claim. The
    service keeps implementation state and competitor references server-owned
    so the Web client cannot promote a planned or gated leaf to implemented.
    """

    def __init__(self, registry_path: str | Path | None = None) -> None:
        configured = registry_path or os.getenv("KJDS_CAPABILITY_ATLAS_PATH")
        self.registry_path = Path(configured) if configured else self._default_path()
        self.registry = self._load()
        self._capabilities = tuple(
            capability
            for domain in self.registry["domains"]
            for capability in domain["capabilities"]
        )
        self._atomic_points = tuple(
            self.registry["operating_graph"]["atomic_points"]
        )
        self.registry_sha256 = self._canonical_hash(self.registry)

    @staticmethod
    def _default_path() -> Path:
        return (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "project"
            / "registries"
            / "cross_border_capability_atlas.json"
        )

    def _load(self) -> dict[str, Any]:
        try:
            registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CapabilityAtlasError(
                f"Unable to load capability atlas: {self.registry_path}"
            ) from exc
        self._validate_registry(registry)
        return registry

    @classmethod
    def _validate_registry(cls, registry: Any) -> None:
        if not isinstance(registry, dict) or registry.get("status") != "active":
            raise CapabilityAtlasError("Capability atlas must be an active object")
        if registry.get("contract_id") != "kjds-cross-border-capability-atlas-v1":
            raise CapabilityAtlasError("Capability atlas contract_id is unsupported")
        if not str(registry.get("registry_version", "")).strip():
            raise CapabilityAtlasError("Capability atlas registry_version is required")
        source_policy = registry.get("source_policy")
        if (
            not isinstance(source_policy, dict)
            or source_policy.get("linkfox_evidence_tier") != "C"
            or source_policy.get("integration_status")
            != "public_workflow_reference_only"
        ):
            raise CapabilityAtlasError(
                "LinkFox must remain a C-tier public workflow reference"
            )
        definitions = registry.get("status_definitions")
        if not isinstance(definitions, dict) or tuple(definitions) != ATLAS_STATUSES:
            raise CapabilityAtlasError(
                "Capability atlas must define canonical statuses in order"
            )
        domains = registry.get("domains")
        if not isinstance(domains, list) or not domains:
            raise CapabilityAtlasError("Capability atlas must define domains")

        domain_ids: set[str] = set()
        capability_ids: set[str] = set()
        for domain in domains:
            if not isinstance(domain, dict):
                raise CapabilityAtlasError("Every capability domain must be an object")
            domain_id = cls._required_text(domain, "id", "domain")
            if domain_id in domain_ids:
                raise CapabilityAtlasError(f"Duplicate capability domain: {domain_id}")
            domain_ids.add(domain_id)
            cls._required_text(domain, "label", domain_id)
            cls._required_text(domain, "mission", domain_id)
            capabilities = domain.get("capabilities")
            if not isinstance(capabilities, list) or not capabilities:
                raise CapabilityAtlasError(
                    f"Capability domain {domain_id} must contain leaves"
                )
            for capability in capabilities:
                cls._validate_capability(capability, domain_id, capability_ids)
        cls._validate_operating_graph(
            registry.get("operating_graph"),
            domain_ids=domain_ids,
            capability_ids=capability_ids,
        )

    @classmethod
    def _validate_operating_graph(
        cls,
        graph: Any,
        *,
        domain_ids: set[str],
        capability_ids: set[str],
    ) -> None:
        if (
            not isinstance(graph, dict)
            or graph.get("contract_id")
            != "kjds-cross-border-operating-graph-v1"
            or graph.get("model") != "point-line-surface"
        ):
            raise CapabilityAtlasError(
                "Capability atlas requires the point-line-surface operating graph"
            )
        model_definition = graph.get("model_definition")
        if (
            not isinstance(model_definition, dict)
            or tuple(model_definition) != ("point", "line", "surface")
        ):
            raise CapabilityAtlasError(
                "Operating graph must define point, line and surface in order"
            )
        source_kinds = graph.get("source_kinds")
        if (
            not isinstance(source_kinds, dict)
            or source_kinds.get("linkfox_public_C", {}).get("evidence_tier") != "C"
        ):
            raise CapabilityAtlasError(
                "Operating graph must preserve LinkFox as C-tier observation"
            )
        profiles = graph.get("contract_profiles")
        if not isinstance(profiles, dict) or not profiles:
            raise CapabilityAtlasError("Operating graph requires contract profiles")
        for profile_id, profile in profiles.items():
            if not isinstance(profile, dict):
                raise CapabilityAtlasError(
                    f"Contract profile {profile_id} must be an object"
                )
            for field in (
                "operation_kind",
                "technology",
                "evidence_gate",
                "failure_queue",
                "readback",
                "sla",
            ):
                cls._required_text(profile, field, profile_id)
            for field in (
                "input_contract",
                "output_contract",
                "failure_modes",
                "kpi",
                "controls",
            ):
                cls._required_text_list(profile, field, profile_id)

        streams = graph.get("value_streams")
        surfaces = graph.get("operating_surfaces")
        points = graph.get("atomic_points")
        if not isinstance(points, list) or not points:
            raise CapabilityAtlasError("Operating graph requires atomic points")
        if not isinstance(streams, list) or not streams:
            raise CapabilityAtlasError("Operating graph requires value streams")
        if not isinstance(surfaces, list) or not surfaces:
            raise CapabilityAtlasError("Operating graph requires operating surfaces")

        stream_ids = cls._unique_object_ids(streams, "value stream")
        point_ids: set[str] = set()
        for point in points:
            if not isinstance(point, dict):
                raise CapabilityAtlasError("Every atomic point must be an object")
            missing = [field for field in REQUIRED_POINT_FIELDS if field not in point]
            if missing:
                raise CapabilityAtlasError(
                    "Atomic point is missing fields: " + ", ".join(missing)
                )
            point_id = cls._required_text(point, "id", "atomic point")
            if point_id in point_ids:
                raise CapabilityAtlasError(f"Duplicate atomic point: {point_id}")
            point_ids.add(point_id)
            if point["domain_id"] not in domain_ids:
                raise CapabilityAtlasError(
                    f"Atomic point {point_id} references unknown domain"
                )
            if point["parent_capability_id"] not in capability_ids:
                raise CapabilityAtlasError(
                    f"Atomic point {point_id} references unknown parent capability"
                )
            if point["contract_profile_id"] not in profiles:
                raise CapabilityAtlasError(
                    f"Atomic point {point_id} references unknown contract profile"
                )
            if point["source_kind"] not in source_kinds:
                raise CapabilityAtlasError(
                    f"Atomic point {point_id} references unknown source kind"
                )
            if point["status"] not in ATLAS_STATUSES:
                raise CapabilityAtlasError(
                    f"Atomic point {point_id} has unknown status"
                )
            for field in (
                "label",
                "objective",
                "business_object",
                "operation_kind",
                "evidence_tier",
                "source_boundary",
                "technology",
                "evidence_gate",
                "failure_queue",
                "readback",
                "sla",
                "owner",
                "reviewer",
                "workspace",
            ):
                cls._required_text(point, field, point_id)
            for field in (
                "input_contract",
                "output_contract",
                "failure_modes",
                "kpi",
                "markets",
                "platforms",
                "controls",
                "value_stream_ids",
            ):
                cls._required_text_list(point, field, point_id)
            if not set(point["value_stream_ids"]) <= stream_ids:
                raise CapabilityAtlasError(
                    f"Atomic point {point_id} references unknown value stream"
                )
            if point["source_kind"] == "linkfox_public_C":
                if point["evidence_tier"] != "C":
                    raise CapabilityAtlasError(
                        f"Atomic point {point_id} promotes LinkFox evidence"
                    )
                if point["status"] == "implemented":
                    raise CapabilityAtlasError(
                        f"Atomic point {point_id} promotes a public observation"
                    )

        for stream in streams:
            missing = [field for field in REQUIRED_STREAM_FIELDS if field not in stream]
            if missing:
                raise CapabilityAtlasError(
                    "Value stream is missing fields: " + ", ".join(missing)
                )
            stream_id = stream["id"]
            for field in (
                "label",
                "mission",
                "entry_gate",
                "exit_gate",
                "human_takeover",
                "sla",
                "adapter_boundary",
            ):
                cls._required_text(stream, field, stream_id)
            for field in (
                "stage_point_ids",
                "object_transitions",
                "events",
                "exceptions",
                "kpi",
            ):
                cls._required_text_list(stream, field, stream_id)
            supporting = stream.get("supporting_point_ids")
            if not isinstance(supporting, list) or any(
                not isinstance(item, str) or not item.strip() for item in supporting
            ):
                raise CapabilityAtlasError(
                    f"Value stream {stream_id} has invalid supporting points"
                )
            refs = stream["stage_point_ids"] + supporting
            if len(refs) != len(set(refs)) or not set(refs) <= point_ids:
                raise CapabilityAtlasError(
                    f"Value stream {stream_id} has duplicate or unknown point refs"
                )

        cls._unique_object_ids(surfaces, "operating surface")
        for surface in surfaces:
            missing = [
                field for field in REQUIRED_SURFACE_FIELDS if field not in surface
            ]
            if missing:
                raise CapabilityAtlasError(
                    "Operating surface is missing fields: " + ", ".join(missing)
                )
            surface_id = surface["id"]
            for field in (
                "label",
                "mission",
                "truth_owner",
                "write_boundary",
            ):
                cls._required_text(surface, field, surface_id)
            for field in (
                "value_stream_ids",
                "focus_point_ids",
                "dimensions",
                "decisions",
                "kpi",
                "alerts",
            ):
                cls._required_text_list(surface, field, surface_id)
            if not set(surface["value_stream_ids"]) <= stream_ids:
                raise CapabilityAtlasError(
                    f"Operating surface {surface_id} references unknown stream"
                )
            if not set(surface["focus_point_ids"]) <= point_ids:
                raise CapabilityAtlasError(
                    f"Operating surface {surface_id} references unknown point"
                )

    @classmethod
    def _validate_capability(
        cls,
        capability: Any,
        domain_id: str,
        capability_ids: set[str],
    ) -> None:
        if not isinstance(capability, dict):
            raise CapabilityAtlasError(
                f"Every capability in {domain_id} must be an object"
            )
        missing = [field for field in REQUIRED_CAPABILITY_FIELDS if field not in capability]
        if missing:
            raise CapabilityAtlasError(
                f"Capability in {domain_id} is missing fields: {', '.join(missing)}"
            )
        capability_id = cls._required_text(capability, "id", domain_id)
        if capability_id in capability_ids:
            raise CapabilityAtlasError(f"Duplicate capability: {capability_id}")
        capability_ids.add(capability_id)
        for field in (
            "label",
            "summary",
            "linkfox",
            "surpass",
            "russia",
            "global",
            "technology",
            "workspace",
        ):
            cls._required_text(capability, field, capability_id)
        if capability["status"] not in ATLAS_STATUSES:
            raise CapabilityAtlasError(
                f"Capability {capability_id} has unknown status"
            )
        for field in ("inputs", "outputs", "markets", "platforms", "controls"):
            value = capability[field]
            if (
                not isinstance(value, list)
                or not value
                or any(not isinstance(item, str) or not item.strip() for item in value)
            ):
                raise CapabilityAtlasError(
                    f"Capability {capability_id} requires non-empty {field}"
                )
        if "RU" not in capability["markets"] and "GLOBAL" not in capability["markets"]:
            raise CapabilityAtlasError(
                f"Capability {capability_id} must declare RU or GLOBAL scope"
            )

    @staticmethod
    def _required_text(container: dict[str, Any], field: str, owner: str) -> str:
        value = container.get(field)
        if not isinstance(value, str) or not value.strip():
            raise CapabilityAtlasError(f"{owner} requires non-empty {field}")
        return value

    @staticmethod
    def _required_text_list(
        container: dict[str, Any], field: str, owner: str
    ) -> list[str]:
        value = container.get(field)
        if (
            not isinstance(value, list)
            or not value
            or any(not isinstance(item, str) or not item.strip() for item in value)
        ):
            raise CapabilityAtlasError(
                f"{owner} requires non-empty {field}"
            )
        return value

    @classmethod
    def _unique_object_ids(cls, items: list[Any], owner: str) -> set[str]:
        identifiers: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                raise CapabilityAtlasError(f"Every {owner} must be an object")
            item_id = cls._required_text(item, "id", owner)
            if item_id in identifiers:
                raise CapabilityAtlasError(f"Duplicate {owner}: {item_id}")
            identifiers.add(item_id)
        return identifiers

    @staticmethod
    def _canonical_hash(value: dict[str, Any]) -> str:
        canonical = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(canonical).hexdigest()

    def snapshot(self) -> dict[str, Any]:
        status_counts = Counter(item["status"] for item in self._capabilities)
        point_status_counts = Counter(item["status"] for item in self._atomic_points)
        point_source_counts = Counter(
            item["source_kind"] for item in self._atomic_points
        )
        point_profile_counts = Counter(
            item["contract_profile_id"] for item in self._atomic_points
        )
        market_counts = Counter(
            market for item in self._capabilities for market in item["markets"]
        )
        platform_counts = Counter(
            platform for item in self._capabilities for platform in item["platforms"]
        )
        linkfox_counts = Counter(
            "not_observed" if "未观察" in item["linkfox"] else "observed"
            for item in self._capabilities
        )
        return {
            "contract_id": self.registry["contract_id"],
            "registry_version": self.registry["registry_version"],
            "last_reviewed": self.registry["last_reviewed"],
            "primary_market": self.registry["primary_market"],
            "primary_platform": self.registry["primary_platform"],
            "source_policy": deepcopy(self.registry["source_policy"]),
            "status_definitions": deepcopy(self.registry["status_definitions"]),
            "technology_principles": list(self.registry["technology_principles"]),
            "counts": {
                "domains": len(self.registry["domains"]),
                "capabilities": len(self._capabilities),
                "atomic_points": len(self._atomic_points),
                "value_streams": len(
                    self.registry["operating_graph"]["value_streams"]
                ),
                "operating_surfaces": len(
                    self.registry["operating_graph"]["operating_surfaces"]
                ),
                "statuses": {
                    status: status_counts.get(status, 0)
                    for status in ATLAS_STATUSES
                },
                "markets": dict(sorted(market_counts.items())),
                "platforms": dict(sorted(platform_counts.items())),
                "linkfox_reference": {
                    "observed": linkfox_counts.get("observed", 0),
                    "not_observed": linkfox_counts.get("not_observed", 0),
                },
                "atomic_point_statuses": {
                    status: point_status_counts.get(status, 0)
                    for status in ATLAS_STATUSES
                },
                "atomic_point_sources": dict(sorted(point_source_counts.items())),
                "contract_profiles": dict(sorted(point_profile_counts.items())),
            },
            "domains": deepcopy(self.registry["domains"]),
            "operating_graph": deepcopy(self.registry["operating_graph"]),
            "registry_sha256": self.registry_sha256,
            "control_envelope": {
                "read_only": True,
                "marketing_claims_are_business_facts": False,
                "linkfox_ozon_integration_verified": False,
                "client_can_promote_status": False,
                "external_write_allowed": False,
                "operating_graph_is_execution_authority": False,
                "expansion_rule": (
                    "official contract, license, least privilege, replay, "
                    "real-sample reconciliation, approval and rollback required"
                ),
            },
        }

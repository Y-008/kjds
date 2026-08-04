from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

CONTRACT_ID = "kjds-global-data-coverage-observation-v1"
REGISTRY_SCHEMA = "kjds-global-source-domain-registry-v1"
MANIFEST_SCHEMA = "kjds-source-coverage-manifest-v1"
NATIVE_CAPS_SCHEMA = "kjds-source-native-caps-v1"

SOURCE_FAMILIES = frozenset(
    {
        "marketplace",
        "customs_trade",
        "company_registry",
        "web_search",
        "social_content",
        "ads_traffic",
        "supplier_catalog",
        "logistics",
        "payments_fx_macro",
        "regulation_standards",
        "ip_patents_research",
        "talent_jobs",
        "crm_erp_finance_operations",
    }
)
DIMENSIONS = frozenset(
    {
        "region",
        "country",
        "language",
        "industry",
        "platform",
        "subject",
        "event",
        "time",
        "data_level",
    }
)
SOURCE_STATUSES = frozenset(
    {"implemented", "contract_only", "blocked", "unsupported"}
)
COMPLETENESS_STATES = frozenset(
    {
        "complete",
        "partial",
        "unknown",
        "missing",
        "blocked",
        "unsupported",
        "not_applicable",
    }
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,239}$")
_EMAIL = re.compile(r"(?i)(?<![\w.+-])[\w.+-]+@[\w.-]+\.[a-z]{2,}(?![\w.-])")
_BEARER = re.compile(r"(?i)authorization\s*:\s*bearer\s+\S+")
_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")


@dataclass(frozen=True, slots=True)
class CoverageObservation:
    contract_id: str
    status: str
    completeness: str
    manifest_ref: str
    source_id: str
    source_family: str
    source_status: str
    as_of: str
    registry_sha256: str
    manifest_sha256: str
    native_caps_sha256: str
    denominator_known: bool
    expected_count: int | None
    observed_count: int
    accepted_count: int
    coverage_gaps: tuple[str, ...]
    blockers: tuple[str, ...]
    conflict_count: int
    full_coverage_claim: bool
    full_coverage_claim_scope: str
    formal_fact: bool = False
    decision: bool = False
    approval: bool = False
    permit: bool = False
    pilot: bool = False
    outbox: bool = False
    canonical_graph_write: bool = False
    external_write: bool = False
    raw_source_retained: bool = False
    observation_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["coverage_gaps"] = list(self.coverage_gaps)
        payload["blockers"] = list(self.blockers)
        return payload


class GlobalDataCoverageWorkspace:
    """Validate bounded global-source coverage without collecting source data."""

    CONTRACT_ID = CONTRACT_ID

    def __init__(self, *, contract_root: Path | None = None) -> None:
        root = contract_root or (
            Path(__file__).resolve().parents[2] / "docs" / "project" / "contracts"
        )
        self._manifest_validator = Draft202012Validator(
            json.loads((root / "source-coverage-manifest-v1.schema.json").read_text("utf-8"))
        )
        self._caps_validator = Draft202012Validator(
            json.loads((root / "source-native-caps-v1.schema.json").read_text("utf-8"))
        )

    def validate(
        self,
        manifest: dict[str, Any],
        native_caps: dict[str, Any],
        registry_snapshot: dict[str, Any],
        as_of: datetime,
    ) -> CoverageObservation:
        cutoff = self._aware(as_of, "as_of")
        self._manifest_validator.validate(manifest)
        self._caps_validator.validate(native_caps)
        self._reject_sensitive_material(manifest)
        self._reject_sensitive_material(native_caps)
        self._reject_sensitive_material(registry_snapshot)
        self._verify_content_hash(manifest, "manifest")
        self._verify_content_hash(native_caps, "native_caps")
        self._validate_registry(registry_snapshot)

        if manifest["as_of"] != cutoff.isoformat():
            raise ValueError("manifest as_of must equal the requested as_of")
        if manifest["registry_sha256"] != registry_snapshot["content_sha256"]:
            raise ValueError("manifest registry hash drift")
        if manifest["native_caps_sha256"] != native_caps["content_sha256"]:
            raise ValueError("manifest native capability hash drift")

        source = manifest["source"]
        if (
            source["source_id"] != native_caps["source_id"]
            or source["source_family"] != native_caps["source_family"]
            or source["source_status"] != native_caps["source_status"]
        ):
            raise ValueError("source and native capability binding drift")
        source_contract = self._registry_source(
            registry_snapshot,
            source_id=source["source_id"],
            source_family=source["source_family"],
        )
        if source_contract["status"] != source["source_status"]:
            raise ValueError("source status drift from registry")
        if source["source_status"] == "implemented" and not source_contract[
            "implementation_evidence_refs"
        ]:
            raise ValueError("implemented source requires implementation Evidence")
        if manifest["universe"]["kind"] != native_caps["universe_kind"]:
            raise ValueError("source universe and native capability drift")
        if manifest["access_contract"] != native_caps["access_contract"]:
            raise ValueError("source access contract drift")
        if not set(manifest["scope"]) == DIMENSIONS:
            raise ValueError("manifest dimensions do not match the global contract")

        self._validate_times(manifest, cutoff)
        self._validate_universe(manifest)
        self._validate_conservation(manifest)
        self._validate_pages(manifest, native_caps)
        self._validate_fields(manifest, native_caps)
        self._validate_window(manifest, cutoff)

        completeness, gaps, blockers = self._classify(
            manifest=manifest,
            source_status=source["source_status"],
            as_of=cutoff,
        )
        requested = manifest["coverage_claim"]["requested_full_coverage"]
        full_claim = requested and completeness == "complete"
        if requested and not full_claim:
            blockers.add("full_coverage_claim_not_proven")

        universe = manifest["universe"]
        conservation = manifest["conservation"]
        observation = CoverageObservation(
            contract_id=CONTRACT_ID,
            status=completeness,
            completeness=completeness,
            manifest_ref=manifest["manifest_ref"],
            source_id=source["source_id"],
            source_family=source["source_family"],
            source_status=source["source_status"],
            as_of=cutoff.isoformat(),
            registry_sha256=registry_snapshot["content_sha256"],
            manifest_sha256=manifest["content_sha256"],
            native_caps_sha256=native_caps["content_sha256"],
            denominator_known=universe["denominator_known"],
            expected_count=universe["expected_count"],
            observed_count=conservation["observed_count"],
            accepted_count=conservation["accepted_count"],
            coverage_gaps=tuple(sorted(gaps)),
            blockers=tuple(sorted(blockers)),
            conflict_count=len(manifest["conflicts"]),
            full_coverage_claim=full_claim,
            full_coverage_claim_scope=(
                manifest["coverage_claim"]["claim_scope"]
                if full_claim
                else "not_proven"
            ),
        )
        return replace(
            observation,
            observation_sha256=content_sha256(observation.to_dict(), omit=()),
        )

    @staticmethod
    def _validate_registry(registry: dict[str, Any]) -> None:
        expected = {
            "schema_version",
            "contract_id",
            "as_of",
            "content_sha256",
            "status_vocabulary",
            "completeness_vocabulary",
            "dimensions",
            "policy",
            "source_families",
        }
        if set(registry) != expected:
            raise ValueError("global source registry fields do not match")
        if registry["schema_version"] != REGISTRY_SCHEMA:
            raise ValueError("global source registry schema mismatch")
        if set(registry["status_vocabulary"]) != SOURCE_STATUSES:
            raise ValueError("global source registry status vocabulary mismatch")
        if set(registry["completeness_vocabulary"]) != COMPLETENESS_STATES:
            raise ValueError("global source registry completeness vocabulary mismatch")
        if set(registry["dimensions"]) != DIMENSIONS:
            raise ValueError("global source registry dimensions mismatch")
        if content_sha256(registry) != registry["content_sha256"]:
            raise ValueError("global source registry content hash drift")
        families = registry["source_families"]
        ids = [item.get("id") for item in families]
        if set(ids) != SOURCE_FAMILIES or len(ids) != len(set(ids)):
            raise ValueError("global source registry family coverage mismatch")
        source_ids: list[str] = []
        for family in families:
            if set(family["required_dimensions"]) != DIMENSIONS:
                raise ValueError("source family dimensions are incomplete")
            if not family["source_contracts"]:
                raise ValueError("source family requires at least one source contract")
            for source in family["source_contracts"]:
                if source["status"] not in SOURCE_STATUSES:
                    raise ValueError("source contract status is invalid")
                if source["family"] != family["id"]:
                    raise ValueError("source contract family drift")
                if source["status"] != "implemented" and source[
                    "implementation_evidence_refs"
                ]:
                    raise ValueError("candidate source cannot claim implementation Evidence")
                source_ids.append(source["id"])
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("global source registry source IDs must be unique")
        policy = registry["policy"]
        required_false = {
            "registry_proves_collection",
            "url_proves_implementation",
            "connector_candidate_proves_implementation",
            "global_label_proves_full_coverage",
            "formal_fact_promotion_allowed",
            "canonical_graph_write_allowed",
            "external_write_allowed",
        }
        if any(policy.get(item) is not False for item in required_false):
            raise ValueError("global source registry control boundary drift")

    @staticmethod
    def _registry_source(
        registry: dict[str, Any], *, source_id: str, source_family: str
    ) -> dict[str, Any]:
        matches = [
            source
            for family in registry["source_families"]
            if family["id"] == source_family
            for source in family["source_contracts"]
            if source["id"] == source_id
        ]
        if len(matches) != 1:
            raise ValueError("source contract is not uniquely registered")
        return matches[0]

    @staticmethod
    def _validate_times(manifest: dict[str, Any], as_of: datetime) -> None:
        captured = GlobalDataCoverageWorkspace._timestamp(
            manifest["captured_at"], "captured_at"
        )
        recorded = GlobalDataCoverageWorkspace._timestamp(
            manifest["recorded_at"], "recorded_at"
        )
        if captured > recorded or recorded > as_of:
            raise ValueError("coverage capture chronology is invalid")
        for evidence in manifest["evidence_refs"]:
            effective = GlobalDataCoverageWorkspace._timestamp(
                evidence["effective_at"], "evidence.effective_at"
            )
            evidence_recorded = GlobalDataCoverageWorkspace._timestamp(
                evidence["recorded_at"], "evidence.recorded_at"
            )
            if effective > as_of or evidence_recorded > as_of:
                raise ValueError("future Evidence cannot support a coverage snapshot")
            if evidence["effective_until"] is not None and as_of >= (
                GlobalDataCoverageWorkspace._timestamp(
                    evidence["effective_until"], "evidence.effective_until"
                )
            ):
                raise ValueError("expired Evidence cannot support a coverage snapshot")

    @staticmethod
    def _validate_universe(manifest: dict[str, Any]) -> None:
        universe = manifest["universe"]
        known = universe["denominator_known"]
        expected = universe["expected_count"]
        evidence = universe["expected_count_evidence_ref"]
        if known and (expected is None or evidence is None):
            raise ValueError("bounded universe requires an evidenced denominator")
        if not known and (expected is not None or evidence is not None):
            raise ValueError("unknown universe cannot declare a denominator")
        if universe["kind"] == "sample_only" and manifest["coverage_claim"][
            "requested_full_coverage"
        ]:
            raise ValueError("sample-only coverage cannot request a full claim")

    @staticmethod
    def _validate_conservation(manifest: dict[str, Any]) -> None:
        item = manifest["conservation"]
        total = (
            item["accepted_count"]
            + item["quarantined_count"]
            + item["failed_count"]
            + item["duplicate_count"]
            + item["suppressed_count"]
        )
        if total != item["source_total"] or item["observed_count"] != item[
            "source_total"
        ]:
            raise ValueError("coverage conservation failed")
        expected = manifest["universe"]["expected_count"]
        if expected is not None and item["expected_count"] != expected:
            raise ValueError("coverage denominator drift")
        if expected is None and item["expected_count"] is not None:
            raise ValueError("unknown denominator leaked into conservation")

    @staticmethod
    def _validate_pages(
        manifest: dict[str, Any], native_caps: dict[str, Any]
    ) -> None:
        pages = manifest["coverage"]["pages"]
        if pages["received_count"] + pages["failed_count"] != pages[
            "expected_count"
        ]:
            raise ValueError("page coverage conservation failed")
        if pages["duplicate_count"] > pages["received_count"]:
            raise ValueError("duplicate page count exceeds received pages")
        pagination = native_caps["capabilities"]["pagination"]
        if pagination["mode"] not in {"none", "export"} and not manifest[
            "checkpoint"
        ]["sha256"]:
            raise ValueError("paged sources require a checkpoint hash")
        if pages["failed_count"] != len(pages["failed_refs"]):
            raise ValueError("failed page register is incomplete")

    @staticmethod
    def _validate_fields(
        manifest: dict[str, Any], native_caps: dict[str, Any]
    ) -> None:
        fields = manifest["coverage"]["fields"]
        buckets = [
            fields["present"],
            fields["missing"],
            fields["unparseable"],
            fields["conflicting"],
        ]
        flattened = [item for bucket in buckets for item in bucket]
        if len(flattened) != len(set(flattened)):
            raise ValueError("field coverage buckets overlap")
        if len(flattened) != fields["required_count"]:
            raise ValueError("field coverage denominator is incomplete")
        native_fields = set(native_caps["capabilities"]["fields"])
        if not set(flattened) <= native_fields:
            raise ValueError("manifest fields exceed declared native capability")

    @staticmethod
    def _validate_window(manifest: dict[str, Any], as_of: datetime) -> None:
        window = manifest["coverage"]["window"]
        requested_start = GlobalDataCoverageWorkspace._timestamp(
            window["requested_start"], "window.requested_start"
        )
        requested_end = GlobalDataCoverageWorkspace._timestamp(
            window["requested_end"], "window.requested_end"
        )
        effective_start = GlobalDataCoverageWorkspace._timestamp(
            window["effective_start"], "window.effective_start"
        )
        effective_end = GlobalDataCoverageWorkspace._timestamp(
            window["effective_end"], "window.effective_end"
        )
        if not requested_start < requested_end <= as_of:
            raise ValueError("requested coverage window is invalid")
        if not effective_start < effective_end <= as_of:
            raise ValueError("effective coverage window is invalid")

    @staticmethod
    def _classify(
        *, manifest: dict[str, Any], source_status: str, as_of: datetime
    ) -> tuple[str, set[str], set[str]]:
        gaps: set[str] = set()
        blockers: set[str] = set()
        if source_status == "unsupported":
            return "unsupported", gaps, {"source_native_capability_unsupported"}
        if source_status == "blocked":
            return "blocked", gaps, {"source_contract_blocked"}
        if source_status == "contract_only":
            return "blocked", gaps, {"source_adapter_not_implemented"}

        universe = manifest["universe"]
        conservation = manifest["conservation"]
        if not universe["denominator_known"]:
            return "unknown", {"source_universe_denominator_unknown"}, blockers
        if conservation["observed_count"] == 0 and universe["expected_count"]:
            return "missing", {"known_source_records_missing"}, blockers

        pages = manifest["coverage"]["pages"]
        fields = manifest["coverage"]["fields"]
        window = manifest["coverage"]["window"]
        freshness = manifest["freshness"]
        if pages["failed_count"] or not pages["closed"]:
            gaps.add("page_coverage_incomplete")
        if fields["missing"]:
            gaps.add("required_fields_missing")
        if fields["unparseable"]:
            gaps.add("required_fields_unparseable")
        if fields["conflicting"] or manifest["conflicts"]:
            gaps.add("source_conflicts_unresolved")
        if window["gaps"] or window["overlaps"]:
            gaps.add("time_window_incomplete")
        if (
            window["requested_start"] != window["effective_start"]
            or window["requested_end"] != window["effective_end"]
        ):
            gaps.add("effective_window_differs_from_requested")
        if conservation["expected_count"] != conservation["observed_count"]:
            gaps.add("record_universe_incomplete")
        if conservation["quarantined_count"] or conservation["failed_count"]:
            gaps.add("record_quality_incomplete")
        if not manifest["checkpoint"]["closed"]:
            gaps.add("checkpoint_open")
        if freshness["status"] != "fresh" or as_of > (
            GlobalDataCoverageWorkspace._timestamp(
                freshness["fresh_until"], "freshness.fresh_until"
            )
        ):
            blockers.add("coverage_snapshot_stale")
        if blockers:
            return "blocked", gaps, blockers
        if gaps or universe["kind"] == "sample_only":
            if universe["kind"] == "sample_only":
                gaps.add("sample_only_universe")
            return "partial", gaps, blockers
        return "complete", gaps, blockers

    @staticmethod
    def _verify_content_hash(payload: dict[str, Any], field: str) -> None:
        declared = str(payload.get("content_sha256") or "")
        if not _HEX64.fullmatch(declared):
            raise ValueError(f"{field} content hash must be a lowercase SHA-256")
        if content_sha256(payload) != declared:
            raise ValueError(f"{field} content hash drift")

    @staticmethod
    def _reject_sensitive_material(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                lowered = str(key).lower()
                if lowered in {
                    "cookie",
                    "token",
                    "credential",
                    "password",
                    "raw_customer_data",
                    "customer_pii",
                }:
                    raise ValueError("coverage contracts cannot contain secret or customer data")
                GlobalDataCoverageWorkspace._reject_sensitive_material(item)
            return
        if isinstance(value, list):
            for item in value:
                GlobalDataCoverageWorkspace._reject_sensitive_material(item)
            return
        if isinstance(value, str) and (
            _EMAIL.search(value) or _BEARER.search(value) or _PRIVATE_KEY.search(value)
        ):
            raise ValueError("coverage contracts cannot contain raw contact or secret material")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("coverage contracts require finite numeric values")

    @staticmethod
    def _aware(value: datetime, field: str) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError(f"{field} must include a timezone")
        return value.astimezone(UTC)

    @staticmethod
    def _timestamp(value: Any, field: str) -> datetime:
        if not isinstance(value, str):
            raise ValueError(f"{field} must be an ISO-8601 timestamp")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
        return GlobalDataCoverageWorkspace._aware(parsed, field)


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def content_sha256(
    payload: dict[str, Any], *, omit: tuple[str, ...] = ("content_sha256",)
) -> str:
    material = {key: value for key, value in payload.items() if key not in omit}
    return hashlib.sha256(canonical_json(material)).hexdigest()

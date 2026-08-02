from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .evidence import EvidenceGrade
from .security import Principal
from .sql_repository import Base

MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 96 * 1024 * 1024
MAX_MEMBER_BYTES = 32 * 1024 * 1024
MAX_MEMBERS = 1_000
CONTRACT_ID = "kjds-market-recon-bundle-v1"

ARTIFACT_KINDS = {
    "full_catalog.json": "ozon_catalog",
    "full_product_info.json": "ozon_product_info",
    "analytics_by_window.json": "ozon_analytics",
    "finance_by_month.json": "ozon_finance",
    "supply_1688/supply_crawl.json": "supplier_catalog",
    "logistics_evidence_hits.json": "logistics_observation",
}
REQUIRED_KINDS = frozenset(
    {
        "ozon_catalog",
        "ozon_product_info",
        "ozon_analytics",
        "ozon_finance",
        "supplier_catalog",
    }
)
LOGISTICS_OBSERVATION_CONTRACT_ID = "kjds-ru002-logistics-observation-v1"
LOGISTICS_COST_LEGS = frozenset(
    {
        "domestic_logistics",
        "international_logistics",
        "packaging",
        "warehousing",
        "customs",
        "last_mile",
        "return",
        "customer_compensation",
        "damage",
    }
)
LOGISTICS_OBSERVATION_FIELDS = frozenset(
    {
        "contract_id",
        "observation_id",
        "source_relpath",
        "source_sha256",
        "source_location",
        "excerpt",
        "source_kind",
        "source_excerpt_sanitized",
        "currency",
        "tax_treatment",
        "validity",
        "mapped_cost_legs",
        "evidence_level",
        "sku_binding",
        "variant_binding",
        "quantity_binding",
        "shipment_profile_binding",
        "effective_period",
        "decision_eligible",
        "actual_cost_created",
        "external_write_allowed",
        "status",
        "observation_sha256",
    }
)
LOGISTICS_SOURCE_KINDS = frozenset({"xlsx", "pdf", "image"})
LOGISTICS_PHONE_PATTERN = re.compile(
    r"(?<!\d)(?:1\d{10}|\+?\d{2,4}[-\s]?\d{6,13})(?!\d)"
)
LOGISTICS_EMAIL_PATTERN = re.compile(
    r"(?i)(?<![\w.+-])[\w.+-]+@[\w.-]+\.[a-z]{2,}(?![\w.-])"
)


class BundleContentConflict(ValueError):
    pass


class MarketReconBundleRunRow(Base):
    __tablename__ = "market_recon_bundle_runs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "idempotency_key",
            name="uq_market_recon_bundle_scope_idempotency",
        ),
        CheckConstraint(
            "length(scope_grant_authority_sha256) = 64 AND length(bundle_sha256) = 64",
            name="ck_market_recon_bundle_hashes",
        ),
        CheckConstraint(
            "status IN ('completed','partial','quarantined')",
            name="ck_market_recon_bundle_status",
        ),
        CheckConstraint(
            "source_total >= 0 AND accepted_count >= 0 AND quarantined_count >= 0 "
            "AND accepted_count + quarantined_count = source_total",
            name="ck_market_recon_bundle_conservation",
        ),
        Index(
            "ix_market_recon_bundle_scope_created",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(180), primary_key=True)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(180), nullable=False)
    contract_id: Mapped[str] = mapped_column(String(100), nullable=False)
    bundle_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    archive_evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence_records.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    source_total: Mapped[int] = mapped_column(Integer, nullable=False)
    accepted_count: Mapped[int] = mapped_column(Integer, nullable=False)
    quarantined_count: Mapped[int] = mapped_column(Integer, nullable=False)
    stage_counts_json: Mapped[dict[str, int]] = mapped_column(JSON, nullable=False)
    quality_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    artifacts_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    imported_by: Mapped[str] = mapped_column(String(240), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MarketReconBundleItemRow(Base):
    __tablename__ = "market_recon_bundle_items"
    __table_args__ = (
        UniqueConstraint(
            "bundle_id",
            "artifact_path",
            "record_index",
            name="uq_market_recon_bundle_item_position",
        ),
        CheckConstraint(
            "length(source_sha256) = 64",
            name="ck_market_recon_bundle_item_hash",
        ),
        CheckConstraint(
            "disposition IN ('accepted','quarantined')",
            name="ck_market_recon_bundle_item_disposition",
        ),
        CheckConstraint(
            "highest_stage IN ('raw_evidence','normalized_observation','reviewed_observation',"
            "'formal_fact','decision_snapshot')",
            name="ck_market_recon_bundle_item_stage",
        ),
        Index(
            "ix_market_recon_bundle_item_scope_kind",
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "artifact_kind",
            "disposition",
        ),
    )

    id: Mapped[str] = mapped_column(String(180), primary_key=True)
    bundle_id: Mapped[str] = mapped_column(
        ForeignKey("market_recon_bundle_runs.id", ondelete="CASCADE"), nullable=False
    )
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    artifact_path: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_kind: Mapped[str] = mapped_column(String(80), nullable=False)
    record_index: Mapped[int] = mapped_column(Integer, nullable=False)
    record_key: Mapped[str] = mapped_column(String(500), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence_records.id"), nullable=False)
    disposition: Mapped[str] = mapped_column(String(30), nullable=False)
    highest_stage: Mapped[str] = mapped_column(String(50), nullable=False)
    reason_codes_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


@dataclass(frozen=True, slots=True)
class _Artifact:
    path: str
    kind: str
    content: bytes


@dataclass(frozen=True, slots=True)
class _Item:
    artifact_path: str
    artifact_kind: str
    record_index: int
    record_key: str
    source_sha256: str
    disposition: str
    highest_stage: str
    reason_codes: tuple[str, ...]
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _ParsedBundle:
    bundle_sha256: str
    artifacts: tuple[_Artifact, ...]
    items: tuple[_Item, ...]
    summary: dict[str, Any]


class MarketReconBundleIngestion:
    """Store a complete recon bundle while keeping quality separate from retention."""

    CONTRACT_ID = CONTRACT_ID

    def __init__(self, *, engine, evidence) -> None:
        self.engine = engine
        self.evidence = evidence

    def preflight(
        self,
        content: bytes,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        scope = self._scope(principal, entity_scope, store_ref, as_of)
        parsed = self._parse(content)
        return {
            "contract_id": self.CONTRACT_ID,
            "status": "ready_for_ingestion",
            "scope": scope,
            "writes_performed": False,
            **parsed.summary,
            "bundle_sha256": parsed.bundle_sha256,
            "external_write_allowed": False,
            "formal_fact_promoted": False,
        }

    def ingest(
        self,
        content: bytes,
        *,
        filename: str,
        idempotency_key: str,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        scope = self._scope(principal, entity_scope, store_ref, as_of)
        idempotency_key = self._required(idempotency_key, "idempotency_key", 180)
        filename = self._required(filename, "filename", 500)
        parsed = self._parse(content)
        with Session(self.engine) as session, session.begin():
            existing = session.scalar(
                select(MarketReconBundleRunRow).where(
                    MarketReconBundleRunRow.tenant_ref == scope["tenant_ref"],
                    MarketReconBundleRunRow.entity_ref == scope["entity_ref"],
                    MarketReconBundleRunRow.store_ref == scope["store_ref"],
                    MarketReconBundleRunRow.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                if existing.bundle_sha256 != parsed.bundle_sha256:
                    raise BundleContentConflict(
                        "Market recon bundle idempotency key already has different immutable content"
                    )
                return self._project(existing, idempotent=True)

            now = datetime.now(UTC)
            bundle_id = new_id("mrb")
            archive_evidence = self.evidence.capture(
                    content=content,
                    filename=filename,
                    content_type="application/zip",
                    source="market-recon-bundle",
                    source_ref=(
                        f"market-recon-bundle://{scope['tenant_ref']}/{scope['entity_ref']}/"
                        f"{scope['store_ref']}/{idempotency_key}"
                    ),
                    grade=EvidenceGrade.C,
                    effective_at=as_of.isoformat(),
                    effective_until=None,
                    created_by=principal.actor_id,
                    metadata={
                        "contract_id": self.CONTRACT_ID,
                        **scope,
                        "bundle_sha256": parsed.bundle_sha256,
                        "retention_class": "operational",
                        "formal_fact": False,
                        "external_write_allowed": False,
                    },
                _session=session,
            )
            evidence_by_path: dict[str, str] = {}
            artifact_summaries: list[dict[str, Any]] = []
            for artifact in parsed.artifacts:
                evidence_record = self.evidence.capture(
                        content=artifact.content,
                        filename=PurePosixPath(artifact.path).name,
                        content_type="application/json",
                        source="market-recon-artifact",
                        source_ref=f"market-recon-artifact://{bundle_id}/{artifact.path}",
                        grade=self._artifact_grade(artifact.kind),
                        effective_at=as_of.isoformat(),
                        effective_until=None,
                        created_by=principal.actor_id,
                        metadata={
                            "contract_id": self.CONTRACT_ID,
                            **scope,
                            "bundle_id": bundle_id,
                            "artifact_path": artifact.path,
                            "artifact_kind": artifact.kind,
                            "retention_class": "financial" if artifact.kind == "ozon_finance" else "operational",
                            "formal_fact": False,
                            "external_write_allowed": False,
                        },
                    _session=session,
                )
                evidence_by_path[artifact.path] = evidence_record.id
                artifact_summaries.append(
                    {
                        "path": artifact.path,
                        "kind": artifact.kind,
                        "byte_size": len(artifact.content),
                        "sha256": evidence_record.sha256,
                        "evidence_id": evidence_record.id,
                    }
                )

            run = MarketReconBundleRunRow(
                    id=bundle_id,
                    tenant_ref=scope["tenant_ref"],
                    entity_ref=scope["entity_ref"],
                    store_ref=scope["store_ref"],
                    scope_grant_authority_sha256=scope["scope_grant_authority_sha256"],
                    idempotency_key=idempotency_key,
                    contract_id=self.CONTRACT_ID,
                    bundle_sha256=parsed.bundle_sha256,
                    archive_evidence_id=archive_evidence.id,
                    status=parsed.summary["status"],
                    source_total=parsed.summary["counts"]["source_total"],
                    accepted_count=parsed.summary["counts"]["accepted"],
                    quarantined_count=parsed.summary["counts"]["quarantined"],
                    stage_counts_json=parsed.summary["stage_counts"],
                    quality_json=parsed.summary["quality"],
                    artifacts_json=artifact_summaries,
                    imported_by=principal.actor_id,
                    as_of=as_of.astimezone(UTC),
                    created_at=now,
            )
            session.add(run)
            session.flush()
            for item in parsed.items:
                session.add(
                    MarketReconBundleItemRow(
                            id=new_id("mri"),
                            bundle_id=bundle_id,
                            tenant_ref=scope["tenant_ref"],
                            entity_ref=scope["entity_ref"],
                            store_ref=scope["store_ref"],
                            artifact_path=item.artifact_path,
                            artifact_kind=item.artifact_kind,
                            record_index=item.record_index,
                            record_key=item.record_key,
                            source_sha256=item.source_sha256,
                            artifact_evidence_id=evidence_by_path[item.artifact_path],
                            disposition=item.disposition,
                            highest_stage=item.highest_stage,
                            reason_codes_json=list(item.reason_codes),
                            payload_json=item.payload,
                            created_at=now,
                    )
                )
            session.flush()
            return self._project(run, idempotent=False)

    def get(
        self,
        bundle_id: str,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        scope = self._scope(principal, entity_scope, store_ref, as_of)
        with Session(self.engine) as session:
            row = session.scalar(
                select(MarketReconBundleRunRow).where(
                    MarketReconBundleRunRow.id == bundle_id,
                    MarketReconBundleRunRow.tenant_ref == scope["tenant_ref"],
                    MarketReconBundleRunRow.entity_ref == scope["entity_ref"],
                    MarketReconBundleRunRow.store_ref == scope["store_ref"],
                    MarketReconBundleRunRow.as_of <= as_of,
                )
            )
            if row is None:
                raise KeyError("Market recon bundle not found in the authorized scope")
            return self._project(row, idempotent=False)

    def quality(
        self,
        bundle_id: str,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        bundle = self.get(
            bundle_id,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        return {
            "contract_id": self.CONTRACT_ID,
            "bundle_id": bundle_id,
            "status": bundle["status"],
            "scope": bundle["scope"],
            "counts": bundle["counts"],
            "stage_counts": bundle["stage_counts"],
            "quality": bundle["quality"],
            "conservation_passed": (
                bundle["counts"]["accepted"] + bundle["counts"]["quarantined"]
                == bundle["counts"]["source_total"]
            ),
            "formal_fact_promoted": False,
            "external_write_allowed": False,
        }

    @classmethod
    def _parse(cls, content: bytes) -> _ParsedBundle:
        if not content or len(content) > MAX_ARCHIVE_BYTES:
            raise ValueError(f"Bundle archive must be between 1 and {MAX_ARCHIVE_BYTES} bytes")
        bundle_sha256 = hashlib.sha256(content).hexdigest()
        try:
            archive = zipfile.ZipFile(io.BytesIO(content))
        except (zipfile.BadZipFile, OSError) as exc:
            raise ValueError("Bundle must be a valid ZIP archive") from exc
        with archive:
            infos = [info for info in archive.infolist() if not info.is_dir()]
            if not infos or len(infos) > MAX_MEMBERS:
                raise ValueError(f"Bundle must contain 1 to {MAX_MEMBERS} files")
            total_uncompressed = 0
            artifacts: list[_Artifact] = []
            seen_paths: set[str] = set()
            for info in infos:
                normalized_path = cls._safe_path(info.filename)
                total_uncompressed += info.file_size
                if info.file_size > MAX_MEMBER_BYTES or total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                    raise ValueError("Bundle exceeds the bounded uncompressed size")
                kind = cls._artifact_kind(normalized_path)
                if kind is None:
                    continue
                canonical_path = cls._canonical_artifact_path(normalized_path, kind)
                if canonical_path in seen_paths:
                    raise ValueError(f"Bundle has duplicate recognized artifact: {canonical_path}")
                seen_paths.add(canonical_path)
                artifacts.append(_Artifact(canonical_path, kind, archive.read(info)))
        present_kinds = {artifact.kind for artifact in artifacts}
        missing = sorted(REQUIRED_KINDS - present_kinds)
        if missing:
            raise ValueError(f"Bundle is missing required artifacts: {', '.join(missing)}")

        items: list[_Item] = []
        artifact_counts: dict[str, int] = {}
        for artifact in sorted(artifacts, key=lambda value: value.path):
            artifact_items = cls._parse_artifact(artifact)
            items.extend(artifact_items)
            artifact_counts[artifact.kind] = artifact_counts.get(artifact.kind, 0) + len(artifact_items)
        accepted = sum(item.disposition == "accepted" for item in items)
        quarantined = len(items) - accepted
        stage_counts = {
            stage: sum(item.highest_stage == stage for item in items)
            for stage in (
                "raw_evidence",
                "normalized_observation",
                "reviewed_observation",
                "formal_fact",
                "decision_snapshot",
            )
        }
        reason_counts: dict[str, int] = {}
        for item in items:
            for reason in item.reason_codes:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
        status = "completed" if quarantined == 0 else "quarantined" if accepted == 0 else "partial"
        summary = {
            "status": status,
            "counts": {
                "source_total": len(items),
                "accepted": accepted,
                "quarantined": quarantined,
            },
            "stage_counts": stage_counts,
            "quality": {
                "artifact_record_counts": dict(sorted(artifact_counts.items())),
                "reason_counts": dict(sorted(reason_counts.items())),
                "decision_eligible_records": stage_counts["formal_fact"] + stage_counts["decision_snapshot"],
                "currency_safe": reason_counts.get("mixed_currency_direct_comparison", 0) == 0,
                "complete_source_retention": accepted + quarantined == len(items),
            },
            "artifacts": [
                {"path": artifact.path, "kind": artifact.kind, "byte_size": len(artifact.content)}
                for artifact in sorted(artifacts, key=lambda value: value.path)
            ],
        }
        return _ParsedBundle(bundle_sha256, tuple(artifacts), tuple(items), summary)

    @classmethod
    def _parse_artifact(cls, artifact: _Artifact) -> list[_Item]:
        try:
            decoded = json.loads(artifact.content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return [
                cls._item(
                    artifact=artifact,
                    index=0,
                    key="parse_error",
                    payload={"raw_sha256": hashlib.sha256(artifact.content).hexdigest()},
                    disposition="quarantined",
                    stage="raw_evidence",
                    reasons=("json_parse_failed", type(exc).__name__),
                )
            ]
        records: list[tuple[str, dict[str, Any]]]
        if artifact.kind == "supplier_catalog" and isinstance(decoded, dict):
            records = [
                (str(category), {"category": str(category), "source": payload})
                for category, payload in sorted(decoded.items(), key=lambda pair: str(pair[0]))
                if isinstance(payload, dict)
            ]
        elif artifact.kind == "browser_capture" and isinstance(decoded, dict):
            records = [(str(decoded.get("url") or artifact.path), decoded)]
        elif artifact.kind == "logistics_observation" and isinstance(
            decoded, list
        ):
            records = [
                (
                    cls._record_key(
                        artifact.kind,
                        payload if isinstance(payload, dict) else {},
                        index,
                    ),
                    payload
                    if isinstance(payload, dict)
                    else {"decoded_type": type(payload).__name__},
                )
                for index, payload in enumerate(decoded)
            ]
        elif isinstance(decoded, list):
            records = [
                (cls._record_key(artifact.kind, payload, index), payload)
                for index, payload in enumerate(decoded)
                if isinstance(payload, dict)
            ]
        else:
            records = []
        if not records:
            return [
                cls._item(
                    artifact=artifact,
                    index=0,
                    key="invalid_shape",
                    payload={"decoded_type": type(decoded).__name__},
                    disposition="quarantined",
                    stage="raw_evidence",
                    reasons=("artifact_shape_invalid",),
                )
            ]

        results: list[_Item] = []
        for index, (key, payload) in enumerate(records):
            disposition, stage, reasons = cls._classify(artifact.kind, payload)
            results.append(
                cls._item(
                    artifact=artifact,
                    index=index,
                    key=key,
                    payload=payload,
                    disposition=disposition,
                    stage=stage,
                    reasons=reasons,
                )
            )
        return results

    @classmethod
    def _classify(cls, kind: str, payload: dict[str, Any]) -> tuple[str, str, tuple[str, ...]]:
        if kind == "ozon_catalog":
            if not payload.get("offer_id") and not payload.get("id"):
                return "quarantined", "raw_evidence", ("product_identity_missing",)
            return "accepted", "normalized_observation", ()
        if kind == "ozon_product_info":
            currency = payload.get("currency_code")
            if not payload.get("offer_id"):
                return "quarantined", "raw_evidence", ("product_identity_missing",)
            if not cls._valid_currency(currency) or not cls._valid_decimal(payload.get("price")):
                return "quarantined", "raw_evidence", ("money_currency_missing",)
            return "accepted", "normalized_observation", ()
        if kind == "ozon_analytics":
            return "accepted", "raw_evidence", ("metric_currency_unverified",)
        if kind == "ozon_finance":
            operations = payload.get("operations") or []
            has_money = any(isinstance(operation, dict) and "amount" in operation for operation in operations)
            if has_money and not cls._valid_currency(payload.get("currency")):
                return "quarantined", "raw_evidence", ("money_currency_missing",)
            return "accepted", "raw_evidence", ()
        if kind == "supplier_catalog":
            source = payload.get("source") or {}
            cards = source.get("supplier_cards") or []
            has_prices = any(isinstance(card, dict) and cls._valid_decimal(card.get("price")) for card in cards)
            reasons: list[str] = ["variant_identity_unresolved"]
            if has_prices and not cls._valid_currency(source.get("currency")):
                reasons.append("money_currency_missing")
            return "quarantined", "raw_evidence", tuple(sorted(reasons))
        if kind == "browser_capture":
            if not payload.get("url") or not payload.get("captured_at"):
                return "quarantined", "raw_evidence", ("capture_identity_missing",)
            return "accepted", "raw_evidence", ("independent_scope_binding_pending",)
        if kind == "logistics_observation":
            if set(payload) != LOGISTICS_OBSERVATION_FIELDS:
                return (
                    "quarantined",
                    "raw_evidence",
                    ("logistics_observation_schema_invalid",),
                )
            required_text = (
                "observation_id",
                "source_relpath",
                "source_location",
                "excerpt",
            )
            if (
                payload.get("contract_id") != LOGISTICS_OBSERVATION_CONTRACT_ID
                or any(
                    not isinstance(payload.get(field), str)
                    or not payload[field].strip()
                    for field in required_text
                )
                or not cls._valid_sha256(payload.get("source_sha256"))
                or not cls._valid_sha256(payload.get("observation_sha256"))
                or payload.get("source_excerpt_sanitized") is not True
                or any(
                    cls._sanitize_logistics_text(payload[field])
                    != payload[field]
                    for field in (
                        "source_relpath",
                        "source_location",
                        "excerpt",
                    )
                )
                or len(payload["excerpt"]) > 1600
                or not cls._valid_logistics_source_path(
                    payload["source_relpath"]
                )
                or not cls._valid_logistics_observation_identity(payload)
            ):
                return (
                    "quarantined",
                    "raw_evidence",
                    ("logistics_observation_identity_missing",),
                )
            unbound_fields = (
                "sku_binding",
                "variant_binding",
                "quantity_binding",
                "shipment_profile_binding",
                "effective_period",
            )
            if any(
                field not in payload or payload.get(field) is not None
                for field in unbound_fields
            ):
                return (
                    "quarantined",
                    "raw_evidence",
                    ("logistics_observation_premature_binding_or_amount",),
                )
            if any(
                payload.get(field) is not False
                for field in (
                    "decision_eligible",
                    "actual_cost_created",
                    "external_write_allowed",
                )
            ) or any(
                (
                    payload.get("evidence_level") != "observed",
                    payload.get("tax_treatment") != "UNKNOWN",
                    payload.get("validity") != "UNKNOWN",
                )
            ):
                return (
                    "quarantined",
                    "raw_evidence",
                    ("logistics_observation_authority_overclaimed",),
                )
            if payload.get("status") != "observed":
                return (
                    "quarantined",
                    "raw_evidence",
                    ("logistics_source_unparsed",),
                )
            if payload.get("source_kind") not in LOGISTICS_SOURCE_KINDS:
                return (
                    "quarantined",
                    "raw_evidence",
                    ("logistics_observation_schema_invalid",),
                )
            currency = payload.get("currency")
            if not cls._valid_currency(currency):
                return (
                    "quarantined",
                    "raw_evidence",
                    ("money_currency_missing",),
                )
            mapped_cost_legs = payload.get("mapped_cost_legs")
            if (
                not isinstance(mapped_cost_legs, list)
                or not mapped_cost_legs
                or any(
                    not isinstance(cost_leg, str)
                    or cost_leg not in LOGISTICS_COST_LEGS
                    for cost_leg in mapped_cost_legs
                )
                or len(set(mapped_cost_legs)) != len(mapped_cost_legs)
            ):
                return (
                    "quarantined",
                    "raw_evidence",
                    ("cost_component_unclassified",),
                )
            return (
                "accepted",
                "normalized_observation",
                (
                    "exact_quantity_missing",
                    "independent_cost_review_pending",
                    "sku_binding_missing",
                    "variant_identity_unresolved",
                ),
            )
        return "quarantined", "raw_evidence", ("artifact_kind_unsupported",)

    @staticmethod
    def _item(
        *,
        artifact: _Artifact,
        index: int,
        key: str,
        payload: dict[str, Any],
        disposition: str,
        stage: str,
        reasons: tuple[str, ...],
    ) -> _Item:
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        return _Item(
            artifact_path=artifact.path,
            artifact_kind=artifact.kind,
            record_index=index,
            record_key=str(key)[:500],
            source_sha256=hashlib.sha256(canonical).hexdigest(),
            disposition=disposition,
            highest_stage=stage,
            reason_codes=tuple(sorted(set(reasons))),
            payload=payload,
        )

    @staticmethod
    def _record_key(kind: str, payload: dict[str, Any], index: int) -> str:
        candidates = {
            "ozon_catalog": ("offer_id", "id"),
            "ozon_product_info": ("offer_id", "id"),
            "ozon_analytics": ("window", "date_from", "from"),
            "ozon_finance": ("month",),
            "logistics_observation": ("observation_id",),
        }.get(kind, ())
        for candidate in candidates:
            if payload.get(candidate) not in (None, ""):
                return str(payload[candidate])
        return f"record-{index}"

    @staticmethod
    def _valid_currency(value: Any) -> bool:
        return isinstance(value, str) and len(value) == 3 and value.isascii() and value.isalpha() and value.isupper()

    @staticmethod
    def _valid_decimal(value: Any) -> bool:
        if value in (None, "") or isinstance(value, (bool, float)):
            return False
        try:
            from decimal import Decimal, InvalidOperation

            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return False
        return parsed.is_finite()

    @staticmethod
    def _valid_sha256(value: Any) -> bool:
        normalized = str(value or "").strip().lower()
        return len(normalized) == 64 and all(
            character in "0123456789abcdef" for character in normalized
        )

    @staticmethod
    def _sanitize_logistics_text(value: str) -> str:
        sanitized = LOGISTICS_PHONE_PATTERN.sub("[REDACTED_PHONE]", value)
        sanitized = LOGISTICS_EMAIL_PATTERN.sub("[REDACTED_EMAIL]", sanitized)
        return re.sub(r"\s+", " ", sanitized).strip()

    @classmethod
    def _valid_logistics_source_path(cls, value: str) -> bool:
        try:
            return cls._safe_path(value) == value
        except ValueError:
            return False

    @classmethod
    def _valid_logistics_observation_identity(
        cls,
        payload: dict[str, Any],
    ) -> bool:
        identity = {
            "contract_id": payload.get("contract_id"),
            "source_relpath": payload.get("source_relpath"),
            "source_sha256": payload.get("source_sha256"),
            "source_location": payload.get("source_location"),
            "excerpt": payload.get("excerpt"),
        }
        identity_digest = hashlib.sha256(
            json.dumps(
                identity,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        observation = dict(payload)
        expected_observation_sha256 = observation.pop(
            "observation_sha256", None
        )
        observation_digest = hashlib.sha256(
            json.dumps(
                observation,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return (
            expected_observation_sha256 == observation_digest
            and payload.get("observation_id")
            == f"ru002_{identity_digest[:24]}"
        )

    @staticmethod
    def _safe_path(value: str) -> str:
        normalized = value.replace("\\", "/")
        path = PurePosixPath(normalized)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("Bundle contains an unsafe archive path")
        return "/".join(part for part in path.parts if part not in ("", "."))

    @staticmethod
    def _artifact_kind(path: str) -> str | None:
        for suffix, kind in ARTIFACT_KINDS.items():
            if path == suffix or path.endswith(f"/{suffix}"):
                return kind
        parts = PurePosixPath(path).parts
        if len(parts) >= 2 and parts[-2] == "browser_capture" and parts[-1].endswith(".json"):
            return "browser_capture"
        return None

    @staticmethod
    def _canonical_artifact_path(path: str, kind: str) -> str:
        if kind == "browser_capture":
            return f"browser_capture/{PurePosixPath(path).name}"
        return next(suffix for suffix, value in ARTIFACT_KINDS.items() if value == kind)

    @staticmethod
    def _artifact_grade(kind: str) -> EvidenceGrade:
        if kind in {"ozon_catalog", "ozon_product_info", "ozon_analytics", "ozon_finance"}:
            return EvidenceGrade.B
        return EvidenceGrade.C

    @staticmethod
    def _required(value: str, field: str, max_length: int) -> str:
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > max_length:
            raise ValueError(f"{field} is required and must be at most {max_length} characters")
        return value.strip()

    @classmethod
    def _scope(
        cls,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, str]:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must include a timezone")
        if as_of > datetime.now(UTC):
            raise ValueError("as_of cannot be in the future")
        if not principal.can_access_store(store_ref):
            raise PermissionError("Authenticated identity is not authorized for store_ref")
        entity_ref = str(entity_scope.get("entity_ref") or "").strip()
        authority = str(entity_scope.get("authority_sha256") or "").strip()
        if entity_scope.get("status") != "ready" or not entity_ref or len(authority) != 64:
            raise ValueError("Market recon bundle ingestion requires one current entity scope grant")
        return {
            "tenant_ref": principal.tenant_ref,
            "entity_ref": entity_ref,
            "store_ref": store_ref,
            "scope_grant_authority_sha256": authority,
        }

    @classmethod
    def _project(cls, row: MarketReconBundleRunRow, *, idempotent: bool) -> dict[str, Any]:
        return {
            "contract_id": row.contract_id,
            "bundle_id": row.id,
            "status": row.status,
            "scope": {
                "tenant_ref": row.tenant_ref,
                "entity_ref": row.entity_ref,
                "store_ref": row.store_ref,
                "scope_grant_authority_sha256": row.scope_grant_authority_sha256,
            },
            "bundle_sha256": row.bundle_sha256,
            "archive_evidence_id": row.archive_evidence_id,
            "counts": {
                "source_total": row.source_total,
                "accepted": row.accepted_count,
                "quarantined": row.quarantined_count,
            },
            "stage_counts": row.stage_counts_json,
            "quality": row.quality_json,
            "artifacts": row.artifacts_json,
            "as_of": row.as_of.isoformat(),
            "created_at": row.created_at.isoformat(),
            "idempotent": idempotent,
            "formal_fact_promoted": False,
            "external_write_allowed": False,
        }

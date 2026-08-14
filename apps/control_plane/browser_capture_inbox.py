from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .evidence import EvidenceGrade
from .security import Principal
from .sql_repository import Base

CAPTURE_CONTRACT = "kjds-browser-capture-envelope/1.1"
SUPPORTED_CAPTURE_CONTRACTS = {
    "kjds-browser-capture-envelope/1.0",
    CAPTURE_CONTRACT,
}
SUPPORTED_EXTRACTORS = {"kjds-visible-dom/1.0", "kjds-visible-dom/1.1"}
PUBLIC_IMAGE_HOST_SUFFIXES = (
    ".1688.com",
    ".alicdn.com",
    ".ozon.ru",
    ".ozone.ru",
    ".ozonusercontent.com",
)
MAX_CAPTURE_AGE = timedelta(days=30)
FUTURE_SKEW = timedelta(minutes=5)
PRICE_SCOPES = {"unit_price", "checkout_total"}
CHECKOUT_PRICE_KIND = "observed_checkout_price"


class BrowserCaptureSubmissionRow(Base):
    __tablename__ = "browser_capture_inbox_submissions"
    __table_args__ = (
        CheckConstraint(
            "("
            "entity_ref IS NULL "
            "AND scope_grant_authority_sha256 IS NULL "
            "AND entity_scope_status IN ('no_data','blocked')"
            ") OR ("
            "entity_ref IS NOT NULL "
            "AND scope_grant_authority_sha256 IS NOT NULL "
            "AND length(scope_grant_authority_sha256) = 64 "
            "AND entity_scope_status = 'ready'"
            ")",
            name="ck_browser_capture_entity_scope_complete",
        ),
        CheckConstraint(
            "length(adapter_contract_sha256) = 64 "
            "AND length(adapter_definition_sha256) = 64 "
            "AND source_grade IN ('A','B','C','D')",
            name="ck_browser_capture_adapter_authority",
        ),
        CheckConstraint(
            "length(request_sha256) = 64 "
            "AND length(evidence_sha256) = 64",
            name="ck_browser_capture_content_hashes",
        ),
        CheckConstraint(
            "status IN ('quarantined','pending_independent_binding')",
            name="ck_browser_capture_status",
        ),
        UniqueConstraint(
            "tenant_ref",
            "store_ref",
            "idempotency_key",
            name="uq_browser_capture_scope_idempotency",
        ),
        Index(
            "ix_browser_capture_scope_observed",
            "tenant_ref",
            "store_ref",
            "observed_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(180), primary_key=True)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str | None] = mapped_column(
        String(160), nullable=True
    )
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_scope_status: Mapped[str] = mapped_column(
        String(20), nullable=False
    )
    scope_grant_authority_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    source_profile: Mapped[str] = mapped_column(String(80), nullable=False)
    marketplace: Mapped[str] = mapped_column(String(40), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_host: Mapped[str] = mapped_column(String(255), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    contract_version: Mapped[str] = mapped_column(String(80), nullable=False)
    adapter_id: Mapped[str] = mapped_column(String(160), nullable=False)
    adapter_version: Mapped[str] = mapped_column(String(80), nullable=False)
    adapter_contract_sha256: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    adapter_definition_sha256: Mapped[str] = mapped_column(
        String(64), nullable=False
    )
    source_grade: Mapped[str] = mapped_column(String(1), nullable=False)
    semantic_authority: Mapped[str] = mapped_column(
        String(160), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_records.id"), nullable=False
    )
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    normalized_payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False
    )
    captured_by: Mapped[str] = mapped_column(String(160), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class BrowserCaptureInbox:
    """Admit one page-capture envelope without promoting business facts."""

    CONTRACT_ID = "kjds-browser-capture-inbox-v1"

    def __init__(
        self,
        *,
        engine,
        evidence,
        scoped_evidence,
        source_adapters,
    ) -> None:
        self.engine = engine
        self.evidence = evidence
        self.scoped_evidence = scoped_evidence
        self.source_adapters = source_adapters

    def preflight(
        self,
        envelope: dict[str, Any],
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        as_of: datetime,
    ) -> dict[str, Any]:
        normalized = self._normalize(
            envelope,
            principal=principal,
            entity_scope=entity_scope,
            as_of=as_of,
        )
        return self._preflight_result(normalized)

    def submit(
        self,
        envelope: dict[str, Any],
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        as_of: datetime,
    ) -> dict[str, Any]:
        normalized = self._normalize(
            envelope,
            principal=principal,
            entity_scope=entity_scope,
            as_of=as_of,
        )
        payload = normalized["payload"]
        request_sha256 = normalized["request_sha256"]
        with Session(self.engine) as session:
            existing = session.scalar(
                select(BrowserCaptureSubmissionRow).where(
                    BrowserCaptureSubmissionRow.tenant_ref
                    == principal.tenant_ref,
                    BrowserCaptureSubmissionRow.store_ref
                    == payload["scope"]["store_ref"],
                    BrowserCaptureSubmissionRow.idempotency_key
                    == payload["idempotency_key"],
                )
            )
            if existing is not None:
                if existing.request_sha256 != request_sha256:
                    raise ValueError(
                        "Browser capture idempotency key already has "
                        "different immutable content"
                    )
                return self._project(
                    existing,
                    principal=principal,
                    entity_scope=entity_scope,
                    as_of=as_of,
                )

        evidence_bytes = self._canonical(payload)
        evidence = self.evidence.capture(
            content=evidence_bytes,
            filename=f"browser-capture-{request_sha256[:16]}.json",
            content_type="application/json",
            source="browser-capture-inbox",
            source_ref=(
                "browser-capture-inbox://"
                f"{principal.tenant_ref}/{payload['scope']['store_ref']}/"
                f"{payload['idempotency_key']}"
            ),
            grade=EvidenceGrade.C,
            effective_at=payload["observed_at"],
            effective_until=None,
            created_by=principal.actor_id,
            metadata={
                "contract_id": self.CONTRACT_ID,
                "capture_contract_version": CAPTURE_CONTRACT,
                "tenant_ref": principal.tenant_ref,
                "entity_ref": payload["scope"]["entity_ref"],
                "store_ref": payload["scope"]["store_ref"],
                "adapter_id": payload["source_adapter"]["adapter_id"],
                "adapter_contract_sha256": payload[
                    "source_adapter"
                ]["adapter_contract_sha256"],
                "semantic_authority": payload[
                    "source_adapter"
                ]["semantic_authority"],
                "retention_class": "operational",
                "external_write_allowed": False,
            },
        )
        now = datetime.now(UTC)
        row = BrowserCaptureSubmissionRow(
            id=new_id("bci"),
            tenant_ref=principal.tenant_ref,
            entity_ref=payload["scope"]["entity_ref"],
            store_ref=payload["scope"]["store_ref"],
            entity_scope_status=payload["scope"]["entity_scope_status"],
            scope_grant_authority_sha256=payload["scope"][
                "scope_grant_authority_sha256"
            ],
            source_profile=payload["source_profile"],
            marketplace=payload["marketplace"],
            source_url=payload["source_url"],
            source_host=payload["source_host"],
            observed_at=self._timestamp(payload["observed_at"], "observed_at"),
            contract_version=payload["contract_version"],
            adapter_id=payload["source_adapter"]["adapter_id"],
            adapter_version=payload["source_adapter"]["adapter_version"],
            adapter_contract_sha256=payload["source_adapter"][
                "adapter_contract_sha256"
            ],
            adapter_definition_sha256=payload["source_adapter"][
                "adapter_definition_sha256"
            ],
            source_grade=payload["source_adapter"]["source_grade"],
            semantic_authority=payload["source_adapter"][
                "semantic_authority"
            ],
            idempotency_key=payload["idempotency_key"],
            request_sha256=request_sha256,
            evidence_id=evidence.id,
            evidence_sha256=evidence.sha256,
            status=(
                "pending_independent_binding"
                if payload["scope"]["entity_ref"]
                else "quarantined"
            ),
            item_count=len(payload["items"]),
            normalized_payload_json=payload,
            captured_by=principal.actor_id,
            captured_at=now,
        )
        try:
            with Session(self.engine) as session, session.begin():
                session.add(row)
                session.flush()
                row_id = row.id
            with Session(self.engine) as session:
                row = session.get(BrowserCaptureSubmissionRow, row_id)
                if row is None:
                    raise RuntimeError(
                        "Browser capture submission disappeared after commit"
                    )
        except IntegrityError as exc:
            with Session(self.engine) as session:
                winner = session.scalar(
                    select(BrowserCaptureSubmissionRow).where(
                        BrowserCaptureSubmissionRow.tenant_ref
                        == principal.tenant_ref,
                        BrowserCaptureSubmissionRow.store_ref
                        == payload["scope"]["store_ref"],
                        BrowserCaptureSubmissionRow.idempotency_key
                        == payload["idempotency_key"],
                    )
                )
                if winner is None:
                    raise
                if winner.request_sha256 != request_sha256:
                    raise ValueError(
                        "Browser capture idempotency key already has "
                        "different immutable content"
                    ) from exc
                row = winner
        return self._project(
            row,
            principal=principal,
            entity_scope=entity_scope,
            as_of=as_of,
        )

    def list(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        limit: int = 100,
    ) -> dict[str, Any]:
        self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        with Session(self.engine) as session:
            rows = list(
                session.scalars(
                    select(BrowserCaptureSubmissionRow)
                    .where(
                        BrowserCaptureSubmissionRow.tenant_ref
                        == principal.tenant_ref,
                        BrowserCaptureSubmissionRow.store_ref == store_ref,
                        BrowserCaptureSubmissionRow.observed_at <= as_of,
                    )
                    .order_by(
                        BrowserCaptureSubmissionRow.observed_at.desc(),
                        BrowserCaptureSubmissionRow.id,
                    )
                    .limit(min(max(limit, 1), 500))
                )
            )
        items = [
            self._project(
                row,
                principal=principal,
                entity_scope=entity_scope,
                as_of=as_of,
            )
            for row in rows
        ]
        payload = {
            "contract_id": self.CONTRACT_ID,
            "status": (
                "no_data"
                if not items
                else "partial"
                if any(
                    item["promotion_readiness"]["status"] != "ready"
                    for item in items
                )
                else "ready"
            ),
            "as_of": self._iso(as_of),
            "scope": {
                "tenant_ref": principal.tenant_ref,
                "entity_ref": (
                    str(entity_scope["entity_ref"])
                    if entity_scope.get("status") == "ready"
                    and entity_scope.get("entity_ref")
                    else None
                ),
                "store_ref": store_ref,
            },
            "items": items,
            "counts": {
                "total": len(items),
                "quarantined": sum(
                    item["status"] == "quarantined" for item in items
                ),
                "pending_independent_binding": sum(
                    item["status"] == "pending_independent_binding"
                    for item in items
                ),
                "ready_for_promotion": sum(
                    item["promotion_readiness"]["status"] == "ready"
                    for item in items
                ),
                "promoted": 0,
            },
            "control_envelope": self._control_envelope(),
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def get(
        self,
        submission_id: str,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        with Session(self.engine) as session:
            row = session.get(BrowserCaptureSubmissionRow, submission_id)
            if (
                row is None
                or row.tenant_ref != principal.tenant_ref
                or row.store_ref != store_ref
                or row.observed_at > as_of
            ):
                raise KeyError(f"Unknown browser capture submission: {submission_id}")
        return self._project(
            row,
            principal=principal,
            entity_scope=entity_scope,
            as_of=as_of,
        )

    def _normalize(
        self,
        envelope: dict[str, Any],
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        as_of: datetime,
    ) -> dict[str, Any]:
        contract_version = str(envelope.get("contract_version") or "")
        if contract_version not in SUPPORTED_CAPTURE_CONTRACTS:
            raise ValueError("Unsupported browser capture contract version")
        if envelope.get("confirmed") is not True:
            raise ValueError("Browser capture requires explicit confirmation")
        store_ref = self._text(
            envelope.get("store_ref"), "store_ref", 160
        )
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        marketplace = self._text(
            envelope.get("marketplace"), "marketplace", 40
        ).lower()
        source_profile = self._text(
            envelope.get("source_profile"), "source_profile", 80
        )
        source_contract = self.source_adapters.browser_capture_contract(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
            source_profile=source_profile,
            marketplace=marketplace,
        )
        if (
            source_contract.get("staging_allowed") is not True
            or source_contract.get("external_write_allowed") is not False
        ):
            raise ValueError("Browser capture adapter does not allow staging")
        adapter = source_contract["adapter"]
        source_url, source_host = self._source_url(
            envelope.get("source_url"),
            adapter=adapter,
            field="source_url",
        )
        observed_at = self._timestamp(
            envelope.get("observed_at"), "observed_at"
        )
        if observed_at > as_of + FUTURE_SKEW:
            raise ValueError("observed_at cannot be in the future")
        if observed_at < as_of - MAX_CAPTURE_AGE:
            raise ValueError("browser capture is stale")
        page = envelope.get("page")
        if not isinstance(page, dict):
            raise ValueError("page must be an object")
        if page.get("extractor_version") not in SUPPORTED_EXTRACTORS:
            raise ValueError("Unsupported browser extractor version")
        if page.get("capture_mode") != "active_tab_visible_dom":
            raise ValueError("Unsupported browser capture mode")
        canonical_url = page.get("canonical_url")
        normalized_canonical = None
        if canonical_url:
            normalized_canonical, _ = self._source_url(
                canonical_url,
                adapter=adapter,
                field="page.canonical_url",
            )
        items = envelope.get("items")
        if not isinstance(items, list) or not 1 <= len(items) <= 50:
            raise ValueError("Browser capture requires 1 to 50 items")
        normalized_items = [
            self._item(
                item,
                marketplace=marketplace,
                source_url=source_url,
                adapter=adapter,
            )
            for item in items
        ]
        fingerprints = [item["fingerprint"] for item in normalized_items]
        if len(set(fingerprints)) != len(fingerprints):
            raise ValueError("Browser capture contains duplicate item keys")
        normalized_items.sort(key=lambda item: item["fingerprint"])
        source_adapter = {
            "adapter_id": adapter["adapter_id"],
            "adapter_version": adapter["adapter_version"],
            "adapter_contract_sha256": source_contract[
                "adapter_contract_sha256"
            ],
            "adapter_definition_sha256": self._hash(adapter),
            "source_grade": adapter["max_source_grade"],
            "semantic_authority": adapter["semantic_authority"],
            "policy": adapter["policy"],
        }
        payload = {
            "contract_version": contract_version,
            "source_profile": source_profile,
            "marketplace": marketplace,
            "source_url": source_url,
            "source_host": source_host,
            "observed_at": self._iso(observed_at),
            "idempotency_key": self._text(
                envelope.get("idempotency_key"),
                "idempotency_key",
                160,
            ),
            "page": {
                "title": self._text(page.get("title"), "page.title", 2000),
                "canonical_url": normalized_canonical,
                "language": (
                    self._text(page["language"], "page.language", 40)
                    if page.get("language")
                    else None
                ),
                "extractor_version": page["extractor_version"],
                "capture_mode": page["capture_mode"],
            },
            "scope": context,
            "source_adapter": source_adapter,
            "items": normalized_items,
            "semantic_limits": {
                "supplier_offer_created": False,
                "actual_cost_created": False,
                "sales_fact_inferred": False,
                "product_created": False,
                "listing_created": False,
                "approval_created": False,
                "permit_created": False,
                "external_write_allowed": False,
            },
        }
        return {
            "payload": payload,
            "request_sha256": self._hash(payload),
        }

    def _item(
        self,
        raw: Any,
        *,
        marketplace: str,
        source_url: str,
        adapter: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise ValueError("Browser capture items must be objects")
        item_url, _ = self._source_url(
            raw.get("source_url") or source_url,
            adapter=adapter,
            field="item.source_url",
        )
        displayed = self._decimal(
            raw.get("displayed_price"), "displayed_price"
        )
        price_scope = str(raw.get("price_scope") or "unit_price").strip()
        if price_scope not in PRICE_SCOPES:
            raise ValueError(
                "price_scope must be unit_price or checkout_total"
            )
        observed_quantity = raw.get("observed_quantity")
        if observed_quantity is not None:
            observed_quantity = int(observed_quantity)
            if observed_quantity < 1:
                raise ValueError("observed_quantity must be positive")
        if price_scope == "checkout_total":
            if observed_quantity is None:
                raise ValueError(
                    "checkout_total requires observed_quantity"
                )
            unit_price = displayed / Decimal(observed_quantity)
        else:
            unit_price = displayed
        price_kind = self._text(
            raw.get("price_kind"), "price_kind", 80
        )
        product_identity = self._string_map(
            raw.get("product_identity"), "product_identity", 40
        )
        external_item_id = self._text(
            raw.get("external_item_id"), "external_item_id", 240
        )
        variant_key = self._text(
            raw.get("variant_key"), "variant_key", 500
        )
        moq = raw.get("min_order_quantity")
        if moq is not None:
            moq = int(moq)
            if moq < 1:
                raise ValueError("min_order_quantity must be positive")
        if price_kind == CHECKOUT_PRICE_KIND:
            if marketplace != "1688":
                raise ValueError(
                    "observed_checkout_price is only supported for 1688"
                )
            if (
                observed_quantity is None
                or raw.get("checkout_verified") is not True
                or raw.get("purchase_available") is not True
                or raw.get("tax_included") is None
                or raw.get("domestic_freight_included") is None
                or not product_identity
                or variant_key.lower() in {"unknown", "default", "unselected"}
            ):
                raise ValueError(
                    "observed_checkout_price requires exact identity, "
                    "selected variant, quantity, checkout verification, "
                    "purchasability and explicit tax/freight boundaries"
                )
            if moq is not None and observed_quantity < moq:
                raise ValueError(
                    "observed checkout quantity cannot be below MOQ"
                )
        natural_key = {
            "marketplace": marketplace,
            "supplier_ref": self._text(
                raw.get("supplier_ref"), "supplier_ref", 240
            ),
            "external_item_id": external_item_id,
            "variant_key": variant_key,
        }
        gaps = []
        if not product_identity:
            gaps.append("exact_product_identity_missing")
        if variant_key.lower() in {"unknown", "default", "unselected"}:
            gaps.append("variant_selection_unverified")
        if price_kind != CHECKOUT_PRICE_KIND:
            gaps.append("checkout_price_not_verified")
        item = {
            **natural_key,
            "fingerprint": self._hash(natural_key),
            "title": self._text(raw.get("title"), "title", 2000),
            "currency": self._text(
                raw.get("currency"), "currency", 3
            ).upper(),
            "displayed_price": format(displayed, "f"),
            "price_scope": price_scope,
            "unit_price": format(unit_price, "f"),
            "price_kind": price_kind,
            "price_contract": (
                "displayed_price_scope_and_server_derived_unit_price/v1"
            ),
            "min_order_quantity": moq,
            "availability": self._text(
                raw.get("availability") or "unknown",
                "availability",
                80,
            ),
            "specifications": self._string_map(
                raw.get("specifications"), "specifications", 80
            ),
            "product_identity": product_identity,
            "observed_quantity": observed_quantity,
            "checkout_verified": raw.get("checkout_verified") is True,
            "tax_included": raw.get("tax_included"),
            "domestic_freight_included": raw.get(
                "domestic_freight_included"
            ),
            "purchase_available": raw.get("purchase_available") is True,
            "media_rights_status": "unverified_external_reference",
            "image_references": self._image_references(
                raw.get("image_references")
            ),
            "source_url": item_url,
            "source_gaps": sorted(gaps),
        }
        item["item_sha256"] = self._hash(item)
        return item

    @staticmethod
    def _image_references(value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list) or len(value) > 20:
            raise ValueError("image_references must contain at most 20 URLs")
        result: list[str] = []
        for raw in value:
            text = str(raw or "").strip()
            if len(text) > 2000:
                raise ValueError("image reference is too long")
            parsed = urlparse(text)
            host = (parsed.hostname or "").lower()
            allowed = parsed.scheme == "https" and any(
                host == suffix[1:] or host.endswith(suffix)
                for suffix in PUBLIC_IMAGE_HOST_SUFFIXES
            )
            if not allowed:
                raise ValueError("image reference must use an admitted public HTTPS host")
            normalized = parsed._replace(query="", fragment="").geturl()
            if normalized not in result:
                result.append(normalized)
        return result

    def _preflight_result(self, normalized: dict[str, Any]) -> dict[str, Any]:
        payload = normalized["payload"]
        entity_ready = bool(payload["scope"]["entity_ref"])
        blockers = []
        semantic_gaps = sorted(
            {
                gap
                for item in payload["items"]
                for gap in item["source_gaps"]
                if gap
                in {
                    "exact_product_identity_missing",
                    "variant_selection_unverified",
                }
            }
        )
        if not entity_ready:
            blockers.append(
                self._blocker(
                    "entity_scope_authority_missing",
                    "identity-governance",
                    "Establish one current independently reviewed entity grant.",
                    "/authority-intake",
                )
            )
        blockers.append(
            self._blocker(
                "evidence_scope_binding_pending_capture",
                "evidence-governance",
                "Save immutable capture Evidence, then complete independent exact-scope binding.",
                "/evidenceops",
            )
        )
        for gap in semantic_gaps:
            blockers.append(
                self._blocker(
                    gap,
                    "market-intelligence",
                    (
                        "Recapture the exact product identity and explicitly "
                        "selected variant from the current product page."
                    ),
                    "/capture-inbox",
                )
            )
        result = {
            "contract_id": self.CONTRACT_ID,
            "status": "ready_with_constraints",
            "capture_allowed": True,
            "request_sha256": normalized["request_sha256"],
            "normalized": payload,
            "capture_state_if_saved": (
                "pending_independent_binding"
                if entity_ready
                else "quarantined"
            ),
            "promotion_readiness": {
                "status": "blocked" if entity_ready else "no_data",
                "source_gaps": [item["code"] for item in blockers],
                "blockers": blockers,
            },
            "control_envelope": self._control_envelope(),
        }
        result["snapshot_sha256"] = self._hash(result)
        return result

    def _project(
        self,
        row: BrowserCaptureSubmissionRow,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        as_of: datetime,
    ) -> dict[str, Any]:
        verification_status = "ready"
        gaps: list[str] = [
            gap
            for item in row.normalized_payload_json["items"]
            for gap in item.get("source_gaps", [])
            if gap
            in {
                "exact_product_identity_missing",
                "variant_selection_unverified",
            }
        ]
        blockers: list[dict[str, Any]] = []
        try:
            verification = self.evidence.verify(row.evidence_id)
            if (
                not verification.valid
                or verification.actual_sha256 != row.evidence_sha256
            ):
                verification_status = "blocked"
                gaps.append("capture_evidence_integrity_invalid")
        except (KeyError, RuntimeError, ValueError):
            verification_status = "blocked"
            gaps.append("capture_evidence_integrity_invalid")

        current_entity_ready = (
            entity_scope.get("status") == "ready"
            and bool(entity_scope.get("entity_ref"))
            and bool(entity_scope.get("authority_sha256"))
        )
        if not current_entity_ready:
            gaps.append("entity_scope_authority_missing")
        adapter_status = "ready"
        try:
            current_contract = (
                self.source_adapters.browser_capture_contract(
                    principal=principal,
                    entity_scope=entity_scope,
                    store_ref=row.store_ref,
                    as_of=as_of,
                    source_profile=row.source_profile,
                    marketplace=row.marketplace,
                )
            )
            if (
                self._hash(current_contract["adapter"])
                != row.adapter_definition_sha256
            ):
                adapter_status = "blocked"
                gaps.append("source_adapter_contract_drift")
        except (PermissionError, ValueError):
            adapter_status = "blocked"
            gaps.append("source_adapter_unavailable")

        binding_status = "no_data"
        if current_entity_ready and verification_status == "ready":
            binding = self.scoped_evidence.project_targets(
                evidence_ids=[row.evidence_id],
                principal=principal,
                entity_scope=entity_scope,
                store_ref=row.store_ref,
                as_of=as_of,
            )
            binding_status = binding["status"]
            if binding_status != "ready":
                gaps.extend(binding["source_gaps"])
        for code in sorted(set(gaps)):
            owner = (
                "identity-governance"
                if code == "entity_scope_authority_missing"
                else "market-intelligence"
                if (
                    "adapter" in code
                    or code
                    in {
                        "exact_product_identity_missing",
                        "variant_selection_unverified",
                    }
                )
                else "evidence-governance"
            )
            blockers.append(
                self._blocker(
                    code,
                    owner,
                    (
                        "Establish one current independently reviewed entity grant."
                        if owner == "identity-governance"
                        else "Re-verify the source and recapture the exact selected variant."
                        if owner == "market-intelligence"
                        else "Verify immutable Evidence and add an independent exact-scope binding."
                    ),
                    (
                        "/authority-intake"
                        if owner == "identity-governance"
                        else "/evidenceops"
                    ),
                )
            )
        promotion_ready = (
            current_entity_ready
            and verification_status == "ready"
            and adapter_status == "ready"
            and binding_status == "ready"
            and not gaps
        )
        return {
            "id": row.id,
            "status": row.status,
            "scope": {
                "tenant_ref": row.tenant_ref,
                "entity_ref": row.entity_ref,
                "store_ref": row.store_ref,
                "entity_scope_status": row.entity_scope_status,
                "scope_grant_authority_sha256": (
                    row.scope_grant_authority_sha256
                ),
            },
            "marketplace": row.marketplace,
            "source_url": row.source_url,
            "source_host": row.source_host,
            "observed_at": self._iso(row.observed_at),
            "captured_at": self._iso(row.captured_at),
            "captured_by": row.captured_by,
            "request_sha256": row.request_sha256,
            "evidence": {
                "evidence_id": row.evidence_id,
                "sha256": row.evidence_sha256,
                "grade": row.source_grade,
                "integrity_status": verification_status,
            },
            "source_adapter": {
                "adapter_id": row.adapter_id,
                "adapter_version": row.adapter_version,
                "adapter_contract_sha256": (
                    row.adapter_contract_sha256
                ),
                "adapter_definition_sha256": (
                    row.adapter_definition_sha256
                ),
                "semantic_authority": row.semantic_authority,
                "current_status": adapter_status,
            },
            "item_count": row.item_count,
            "items": row.normalized_payload_json["items"],
            "contract_version": row.contract_version,
            "promotion_readiness": {
                "status": "ready" if promotion_ready else (
                    "no_data"
                    if not current_entity_ready
                    else "blocked"
                ),
                "source_gaps": sorted(set(gaps)),
                "blockers": blockers,
                "observation_promotion_route_exposed": False,
            },
            "control_envelope": self._control_envelope(),
        }

    @staticmethod
    def _control_envelope() -> dict[str, Any]:
        return {
            "internal_evidence_write_only": True,
            "formal_observation_created": False,
            "supplier_offer_created": False,
            "actual_cost_created": False,
            "product_created": False,
            "listing_created": False,
            "approval_created": False,
            "permit_created": False,
            "external_write_allowed": False,
        }

    @staticmethod
    def _blocker(
        code: str,
        owner: str,
        next_action: str,
        next_workspace: str,
    ) -> dict[str, Any]:
        return {
            "code": code,
            "severity": "P0" if "integrity" in code else "P1",
            "owner": owner,
            "sla": "before Marketplace Observation promotion",
            "next": next_action,
            "next_workspace": next_workspace,
        }

    @staticmethod
    def _context(
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise ValueError("as_of must include a timezone")
        if not principal.can_access_store(store_ref):
            raise PermissionError(
                "Authenticated identity is not authorized for store_ref"
            )
        ready = (
            entity_scope.get("status") == "ready"
            and bool(entity_scope.get("entity_ref"))
            and bool(entity_scope.get("authority_sha256"))
        )
        return {
            "tenant_ref": principal.tenant_ref,
            "entity_ref": (
                str(entity_scope["entity_ref"]) if ready else None
            ),
            "store_ref": store_ref,
            "entity_scope_status": (
                "ready"
                if ready
                else "blocked"
                if entity_scope.get("status") == "blocked"
                else "no_data"
            ),
            "scope_grant_authority_sha256": (
                str(entity_scope["authority_sha256"]) if ready else None
            ),
            "scope_as_of": BrowserCaptureInbox._iso(as_of),
        }

    @classmethod
    def _source_url(
        cls,
        value: Any,
        *,
        adapter: dict[str, Any],
        field: str,
    ) -> tuple[str, str]:
        text = cls._text(value, field, 2000)
        parsed = urlparse(text)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not host:
            raise ValueError(f"{field} must be an HTTPS URL")
        allowed = [
            str(item).lower() for item in adapter.get("allowed_hosts", [])
        ]
        if not any(host == item or host.endswith(f".{item}") for item in allowed):
            raise ValueError(
                f"{field} is outside the frozen source adapter"
            )
        return text, host

    @staticmethod
    def _decimal(value: Any, field: str) -> Decimal:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError) as exc:
            raise ValueError(f"{field} must be a decimal") from exc
        if not parsed.is_finite() or parsed <= 0:
            raise ValueError(f"{field} must be positive")
        return parsed

    @classmethod
    def _string_map(
        cls,
        value: Any,
        field: str,
        max_keys: int,
    ) -> dict[str, str]:
        if value is None:
            return {}
        if not isinstance(value, dict) or len(value) > max_keys:
            raise ValueError(
                f"{field} must be an object with at most {max_keys} keys"
            )
        return {
            cls._text(key, f"{field} key", 100): cls._text(
                item, f"{field} value", 500
            )
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }

    @staticmethod
    def _text(value: Any, field: str, max_length: int) -> str:
        text = str(value or "").strip()
        if not text or len(text) > max_length:
            raise ValueError(
                f"{field} must contain 1 to {max_length} characters"
            )
        return text

    @staticmethod
    def _timestamp(value: Any, field: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(
                str(value).replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ValueError(f"{field} must be ISO-8601") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(f"{field} must include a timezone")
        return parsed.astimezone(UTC)

    @staticmethod
    def _iso(value: datetime) -> str:
        if value.tzinfo is None or value.utcoffset() is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat()

    @staticmethod
    def _canonical(value: Any) -> bytes:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")

    @classmethod
    def _hash(cls, value: Any) -> str:
        return hashlib.sha256(cls._canonical(value)).hexdigest()

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

CAPTURE_CONTRACT = "kjds-browser-capture-envelope/1.2"
SUPPORTED_CAPTURE_CONTRACTS = {
    "kjds-browser-capture-envelope/1.0",
    "kjds-browser-capture-envelope/1.1",
    CAPTURE_CONTRACT,
}
SUPPORTED_EXTRACTORS = {
    "kjds-visible-dom/1.0",
    "kjds-visible-dom/1.1",
    "kjds-visible-dom/1.2",
}
CAPTURE_KINDS = {
    "product_detail_variant_matrix",
    "search_result_candidates",
    "store_catalog_candidates",
    "generic_product",
}
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
        sourcing_comparison = self._cross_offer_comparison(items)
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
            "sourcing_comparison": sourcing_comparison,
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
        capture_kind = str(page.get("capture_kind") or "generic_product")
        if capture_kind not in CAPTURE_KINDS:
            raise ValueError("Unsupported browser capture kind")
        canonical_url = page.get("canonical_url")
        normalized_canonical = None
        if canonical_url:
            normalized_canonical, _ = self._source_url(
                canonical_url,
                adapter=adapter,
                field="page.canonical_url",
            )
        items = envelope.get("items")
        item_limit = (
            500
            if contract_version == CAPTURE_CONTRACT
            and capture_kind == "product_detail_variant_matrix"
            else 50
        )
        if not isinstance(items, list) or not 1 <= len(items) <= item_limit:
            raise ValueError(
                f"Browser capture requires 1 to {item_limit} items"
            )
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
        if capture_kind == "product_detail_variant_matrix":
            offer_ids = {
                item["external_item_id"] for item in normalized_items
            }
            supplier_refs = {
                item["supplier_ref"] for item in normalized_items
            }
            if len(offer_ids) != 1 or len(supplier_refs) != 1:
                raise ValueError(
                    "product detail capture must bind one offer and supplier"
                )
            raw_coverage = page.get("capture_coverage") or {}
            if (
                raw_coverage.get("discovered_count") != len(normalized_items)
                or raw_coverage.get("captured_count") != len(normalized_items)
                or raw_coverage.get("truncated") is not False
            ):
                raise ValueError(
                    "product detail capture must preserve the full SKU matrix"
                )
            if any(
                not item["product_identity"].get("sku_id")
                or not item["product_identity"].get("spec_id")
                for item in normalized_items
            ):
                raise ValueError(
                    "product detail capture requires sku_id and spec_id for every row"
                )
        elif capture_kind in {
            "search_result_candidates",
            "store_catalog_candidates",
        }:
            if any(
                item["variant_key"].lower() != "unselected"
                for item in normalized_items
            ):
                raise ValueError(
                    "candidate card capture cannot claim selected variants"
                )
        coverage = self._signal_object(
            page.get("capture_coverage"),
            "page.capture_coverage",
            20,
        )
        discovered = coverage.get("discovered_count")
        captured = coverage.get("captured_count")
        if (
            isinstance(discovered, int)
            and isinstance(captured, int)
            and (discovered < captured or captured != len(normalized_items))
        ):
            raise ValueError(
                "capture coverage must preserve discovered/captured counts"
            )
        merchant = self._merchant(
            envelope.get("merchant"),
            item_supplier_refs={
                item["supplier_ref"] for item in normalized_items
            },
        )
        variant_summary = self._variant_summary(normalized_items)
        erp_staging = self._erp_staging(
            normalized_items,
            observed_at=self._iso(observed_at),
            merchant=merchant,
            capture_context={
                "capture_kind": capture_kind,
                "provider_id": self._optional_text(
                    page.get("provider_id"), "page.provider_id", 160
                ),
                "provider_version": self._optional_text(
                    page.get("provider_version"),
                    "page.provider_version",
                    80,
                ),
                "structured_data_source": self._optional_text(
                    page.get("structured_data_source"),
                    "page.structured_data_source",
                    160,
                ),
                "capture_coverage": coverage,
            },
        )
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
                "capture_kind": capture_kind,
                "provider_id": self._optional_text(
                    page.get("provider_id"), "page.provider_id", 160
                ),
                "provider_version": self._optional_text(
                    page.get("provider_version"),
                    "page.provider_version",
                    80,
                ),
                "structured_data_source": self._optional_text(
                    page.get("structured_data_source"),
                    "page.structured_data_source",
                    160,
                ),
                "search_query": self._optional_text(
                    page.get("search_query"), "page.search_query", 500
                ),
                "capture_coverage": coverage,
            },
            "merchant": merchant,
            "scope": context,
            "source_adapter": source_adapter,
            "items": normalized_items,
            "variant_summary": variant_summary,
            "erp_staging": erp_staging,
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
        identity_offer_id = product_identity.get(
            "offer_id", product_identity.get("external_item_id")
        )
        if identity_offer_id and identity_offer_id != external_item_id:
            raise ValueError(
                "product_identity offer_id must match external_item_id"
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
        comparison_dimensions = self._string_map(
            raw.get("comparison_dimensions"),
            "comparison_dimensions",
            40,
        )
        natural_key = {
            "marketplace": marketplace,
            "supplier_ref": self._text(
                raw.get("supplier_ref"), "supplier_ref", 240
            ),
            "external_item_id": external_item_id,
            "sku_id": product_identity.get("sku_id"),
            "spec_id": product_identity.get("spec_id"),
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
            "comparison_dimensions": comparison_dimensions,
            "comparison_key_sha256": (
                self._hash(
                    {
                        "currency": self._text(
                            raw.get("currency"), "currency", 3
                        ).upper(),
                        "dimensions": comparison_dimensions,
                    }
                )
                if comparison_dimensions
                else None
            ),
            "observed_quantity": observed_quantity,
            "checkout_verified": raw.get("checkout_verified") is True,
            "tax_included": raw.get("tax_included"),
            "domestic_freight_included": raw.get(
                "domestic_freight_included"
            ),
            "purchase_available": raw.get("purchase_available") is True,
            "confidence": format(
                self._confidence(raw.get("confidence", "0.5")), "f"
            ),
            "market_signals": self._signal_object(
                raw.get("market_signals"), "market_signals", 80
            ),
            "supply_signals": self._signal_object(
                raw.get("supply_signals"), "supply_signals", 80
            ),
            "experiment_readbacks": self._signal_object(
                raw.get("experiment_readbacks"),
                "experiment_readbacks",
                20,
            ),
            "target_product_id": self._optional_text(
                raw.get("target_product_id"), "target_product_id", 160
            ),
            "target_offer_id": self._optional_text(
                raw.get("target_offer_id"), "target_offer_id", 160
            ),
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
                    "exact_sku_identity_missing",
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
                "exact_sku_identity_missing",
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
                        "exact_sku_identity_missing",
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
            "page": row.normalized_payload_json.get("page", {}),
            "merchant": row.normalized_payload_json.get("merchant"),
            "variant_summary": row.normalized_payload_json.get(
                "variant_summary", []
            ),
            "erp_staging": row.normalized_payload_json.get(
                "erp_staging",
                {"status": "legacy_capture", "rows": []},
            ),
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

    @classmethod
    def _merchant(
        cls,
        value: Any,
        *,
        item_supplier_refs: set[str],
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("merchant must be an object")
        supplier_ref = cls._text(
            value.get("supplier_ref"), "merchant.supplier_ref", 240
        )
        if supplier_ref not in item_supplier_refs:
            raise ValueError(
                "merchant supplier_ref must match a captured item supplier_ref"
            )
        return {
            "supplier_ref": supplier_ref,
            "company_name": cls._optional_text(
                value.get("company_name"), "merchant.company_name", 500
            ),
            "login_id": cls._optional_text(
                value.get("login_id"), "merchant.login_id", 240
            ),
            "public_signals": cls._signal_object(
                value.get("public_signals"),
                "merchant.public_signals",
                80,
            ),
        }

    @classmethod
    def _variant_summary(
        cls,
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            groups.setdefault(item["external_item_id"], []).append(item)
        result: list[dict[str, Any]] = []
        for external_item_id, rows in sorted(groups.items()):
            currencies = {row["currency"] for row in rows}
            if len(currencies) != 1:
                raise ValueError("one offer cannot contain multiple currencies")
            prices = [Decimal(row["unit_price"]) for row in rows]
            minimum = min(prices)
            maximum = max(prices)
            minimum_rows = [
                cls._variant_ref(row)
                for row in rows
                if Decimal(row["unit_price"]) == minimum
            ]
            comparison_buckets: dict[str, list[dict[str, Any]]] = {}
            for row in rows:
                key = row.get("comparison_key_sha256")
                if not key:
                    key = f"unresolved:{row['fingerprint']}"
                comparison_buckets.setdefault(key, []).append(row)
            comparison_groups = []
            for key, comparable_rows in sorted(comparison_buckets.items()):
                comparable_prices = [
                    Decimal(row["unit_price"]) for row in comparable_rows
                ]
                group_minimum = min(comparable_prices)
                comparison_groups.append(
                    {
                        "comparison_key_sha256": (
                            None if key.startswith("unresolved:") else key
                        ),
                        "comparison_dimensions": comparable_rows[0].get(
                            "comparison_dimensions", {}
                        ),
                        "status": (
                            "comparable"
                            if not key.startswith("unresolved:")
                            else "requires_dimension_alignment"
                        ),
                        "item_count": len(comparable_rows),
                        "minimum_unit_price": format(group_minimum, "f"),
                        "maximum_unit_price": format(
                            max(comparable_prices), "f"
                        ),
                        "minimum_variants": [
                            cls._variant_ref(row)
                            for row in comparable_rows
                            if Decimal(row["unit_price"]) == group_minimum
                        ],
                    }
                )
            result.append(
                {
                    "external_item_id": external_item_id,
                    "currency": next(iter(currencies)),
                    "variant_count": len(rows),
                    "minimum_unit_price": format(minimum, "f"),
                    "maximum_unit_price": format(maximum, "f"),
                    "minimum_variants": minimum_rows,
                    "stock_counts": {
                        "in_stock": sum(
                            row["availability"] == "in_stock" for row in rows
                        ),
                        "out_of_stock": sum(
                            row["availability"] == "out_of_stock"
                            for row in rows
                        ),
                        "unknown": sum(
                            row["availability"]
                            not in {"in_stock", "out_of_stock"}
                            for row in rows
                        ),
                    },
                    "comparison_groups": comparison_groups,
                    "comparison_rule": (
                        "only_equal_server_normalized_dimensions_are_comparable"
                    ),
                }
            )
        return result

    @staticmethod
    def _variant_ref(item: dict[str, Any]) -> dict[str, Any]:
        identity = item.get("product_identity", {})
        return {
            "fingerprint": item["fingerprint"],
            "sku_id": identity.get("sku_id"),
            "spec_id": identity.get("spec_id"),
            "variant_key": item["variant_key"],
            "unit_price": item["unit_price"],
            "comparison_key_sha256": item.get("comparison_key_sha256"),
        }

    @classmethod
    def _erp_staging(
        cls,
        items: list[dict[str, Any]],
        *,
        observed_at: str,
        merchant: dict[str, Any] | None,
        capture_context: dict[str, Any],
    ) -> dict[str, Any]:
        rows = []
        for item in items:
            identity = item["product_identity"]
            exact = bool(
                identity.get("sku_id")
                and identity.get("spec_id")
                and item["variant_key"].lower()
                not in {"unknown", "default", "unselected"}
            )
            rows.append(
                {
                    "staging_key": item["fingerprint"],
                    "mapping_status": (
                        "exact_variant_staged"
                        if exact
                        else "requires_detail_enrichment"
                    ),
                    "marketplace": item["marketplace"],
                    "supplier_ref": item["supplier_ref"],
                    "supplier_public_profile": (
                        json.loads(json.dumps(merchant, ensure_ascii=False))
                        if merchant is not None
                        else None
                    ),
                    "offer_id": item["external_item_id"],
                    "sku_id": identity.get("sku_id"),
                    "spec_id": identity.get("spec_id"),
                    "variant_key": item["variant_key"],
                    "title": item["title"],
                    "product_identity": identity,
                    "currency": item["currency"],
                    "displayed_price": item["displayed_price"],
                    "price_scope": item["price_scope"],
                    "unit_price": item["unit_price"],
                    "price_kind": item["price_kind"],
                    "price_contract": item["price_contract"],
                    "min_order_quantity": item[
                        "min_order_quantity"
                    ],
                    "availability": item["availability"],
                    "specifications": item["specifications"],
                    "comparison_dimensions": item[
                        "comparison_dimensions"
                    ],
                    "comparison_key_sha256": item.get(
                        "comparison_key_sha256"
                    ),
                    "observed_quantity": item["observed_quantity"],
                    "checkout_verified": item["checkout_verified"],
                    "tax_included": item["tax_included"],
                    "domestic_freight_included": item[
                        "domestic_freight_included"
                    ],
                    "purchase_available": item["purchase_available"],
                    "confidence": item["confidence"],
                    "market_signals": item["market_signals"],
                    "supply_signals": item["supply_signals"],
                    "experiment_readbacks": item[
                        "experiment_readbacks"
                    ],
                    "target_product_id": item["target_product_id"],
                    "target_offer_id": item["target_offer_id"],
                    "media_rights_status": item[
                        "media_rights_status"
                    ],
                    "image_references": item["image_references"],
                    "source_gaps": item["source_gaps"],
                    "source_observed_at": observed_at,
                    "source_capture": json.loads(
                        json.dumps(capture_context, ensure_ascii=False)
                    ),
                    "source_url": item["source_url"],
                    "item_sha256": item["item_sha256"],
                    # Preserve the complete validated observation as the
                    # immutable audit payload.  Flattened fields above are
                    # indexes for ERP consumers; this copy prevents any
                    # future admitted public signal from being dropped at
                    # the staging boundary.
                    "source_observation": json.loads(
                        json.dumps(item, ensure_ascii=False)
                    ),
                }
            )
        exact_count = sum(
            row["mapping_status"] == "exact_variant_staged" for row in rows
        )
        return {
            "contract_id": "kjds-erp-sourcing-staging/1.1",
            "status": (
                "exact_variant_staged"
                if exact_count == len(rows)
                else "partial_requires_detail_enrichment"
            ),
            "row_count": len(rows),
            "exact_variant_count": exact_count,
            "rows": rows,
            "formal_product_write": False,
            "supplier_offer_write": False,
            "external_write": False,
        }

    @classmethod
    def _cross_offer_comparison(
        cls,
        captures: list[dict[str, Any]],
        *,
        reference_quantity: int = 1,
    ) -> dict[str, Any]:
        """Compare only latest, intact, exact-detail rows across offers."""
        snapshots_by_offer: dict[
            tuple[str, str], list[dict[str, Any]]
        ] = {}
        candidate_capture_count = 0
        candidate_row_count = 0
        excluded_capture_count = 0
        for capture in captures:
            if (
                capture["evidence"]["integrity_status"] != "ready"
                or capture["source_adapter"]["current_status"] != "ready"
            ):
                excluded_capture_count += 1
                continue
            capture_kind = capture.get("page", {}).get("capture_kind")
            if capture_kind in {
                "search_result_candidates",
                "store_catalog_candidates",
            }:
                candidate_capture_count += 1
                candidate_row_count += len(capture.get("items", []))
                continue
            if capture_kind != "product_detail_variant_matrix":
                continue
            capture_items = capture.get("items", [])
            if not capture_items:
                continue
            first = capture_items[0]
            offer_key = (
                capture["marketplace"],
                first["external_item_id"],
            )
            snapshots_by_offer.setdefault(offer_key, []).append(capture)

        latest_by_offer: dict[tuple[str, str], dict[str, Any]] = {}
        supplier_drift_offer_count = 0
        for offer_key, snapshots in snapshots_by_offer.items():
            supplier_refs = {
                item["supplier_ref"]
                for snapshot in snapshots
                for item in snapshot.get("items", [])[:1]
            }
            if len(supplier_refs) != 1:
                supplier_drift_offer_count += 1
                excluded_capture_count += len(snapshots)
                continue
            # Captures are already newest-first. Do not count historical
            # snapshots of one offer as additional suppliers.
            latest_by_offer[offer_key] = snapshots[0]

        buckets: dict[str, dict[str, Any]] = {}
        unresolved_rows = 0
        for capture in latest_by_offer.values():
            for item in capture.get("items", []):
                identity = item.get("product_identity", {})
                dimensions = item.get("comparison_dimensions", {})
                discriminators = {
                    key
                    for key in {"pack_count", "size", "material"}
                    if dimensions.get(key)
                }
                comparison_ready = bool(
                    identity.get("sku_id")
                    and identity.get("spec_id")
                    and item.get("comparison_key_sha256")
                    and dimensions.get("category_id")
                    and dimensions.get("trade_unit")
                    and len(discriminators) >= 2
                )
                if not comparison_ready:
                    unresolved_rows += 1
                    continue
                price_basis = (
                    f"{item['price_kind']}:{item['price_scope']}"
                )
                group_identity = {
                    "marketplace": capture["marketplace"],
                    "comparison_key_sha256": item[
                        "comparison_key_sha256"
                    ],
                    "price_basis": price_basis,
                }
                group_key = cls._hash(group_identity)
                bucket = buckets.setdefault(
                    group_key,
                    {
                        "comparison_group_sha256": group_key,
                        **group_identity,
                        "currency": item["currency"],
                        "comparison_dimensions": dimensions,
                        "rows": [],
                    },
                )
                moq = item.get("min_order_quantity")
                if (
                    item["price_kind"] != "public_display_price"
                    or item["price_scope"] != "unit_price"
                ):
                    eligibility = "price_basis_not_public_unit"
                elif item.get("availability") == "out_of_stock":
                    eligibility = "out_of_stock"
                elif item.get("availability") != "in_stock":
                    eligibility = "availability_unverified"
                elif moq is None:
                    eligibility = "moq_unverified"
                elif moq > reference_quantity:
                    eligibility = "reference_quantity_below_moq"
                else:
                    eligibility = "eligible_public_display_price"
                bucket["rows"].append(
                    {
                        "capture_id": capture["id"],
                        "observed_at": capture["observed_at"],
                        "supplier_ref": item["supplier_ref"],
                        "offer_id": item["external_item_id"],
                        "sku_id": identity["sku_id"],
                        "spec_id": identity["spec_id"],
                        "variant_key": item["variant_key"],
                        "unit_price": item["unit_price"],
                        "currency": item["currency"],
                        "min_order_quantity": moq,
                        "availability": item["availability"],
                        "eligibility": eligibility,
                        "source_url": item["source_url"],
                        "item_sha256": item["item_sha256"],
                    }
                )

        groups = []
        for bucket in buckets.values():
            rows = sorted(
                bucket.pop("rows"),
                key=lambda row: (
                    Decimal(row["unit_price"]),
                    row["supplier_ref"],
                    row["offer_id"],
                    row["sku_id"],
                    row["spec_id"],
                ),
            )
            eligible = [
                row
                for row in rows
                if row["eligibility"]
                == "eligible_public_display_price"
            ]
            eligible_offers = {
                (row["supplier_ref"], row["offer_id"])
                for row in eligible
            }
            minimum = (
                min(Decimal(row["unit_price"]) for row in eligible)
                if eligible
                else None
            )
            groups.append(
                {
                    **bucket,
                    "status": (
                        "comparable"
                        if len(eligible_offers) >= 2
                        else "insufficient_exact_offers"
                    ),
                    "exact_offer_count": len(
                        {
                            (row["supplier_ref"], row["offer_id"])
                            for row in rows
                        }
                    ),
                    "exact_row_count": len(rows),
                    "eligible_offer_count": len(eligible_offers),
                    "eligible_row_count": len(eligible),
                    "minimum_eligible_unit_price": (
                        format(minimum, "f") if minimum is not None else None
                    ),
                    "lowest_rows": (
                        [
                            row
                            for row in eligible
                            if Decimal(row["unit_price"]) == minimum
                        ]
                        if minimum is not None
                        else []
                    ),
                    "rows": rows,
                }
            )
        groups.sort(
            key=lambda group: (
                group["marketplace"],
                json.dumps(
                    group["comparison_dimensions"],
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                group["price_basis"],
            )
        )
        return {
            "contract_id": "kjds-sourcing-comparison/1.0",
            "status": (
                "comparable"
                if any(group["status"] == "comparable" for group in groups)
                else "requires_more_exact_offers"
                if groups or candidate_row_count
                else "no_data"
            ),
            "reference_quantity": reference_quantity,
            "latest_exact_offer_count": len(latest_by_offer),
            "candidate_capture_count": candidate_capture_count,
            "candidate_row_count": candidate_row_count,
            "excluded_capture_count": excluded_capture_count,
            "supplier_drift_offer_count": supplier_drift_offer_count,
            "unresolved_exact_row_count": unresolved_rows,
            "groups": groups,
            "comparison_rule": (
                "latest_intact_exact_detail_rows_with_equal_server_"
                "normalized_dimensions_and_explicit_moq"
            ),
            "formal_cost_created": False,
            "freight_included": False,
            "tax_included": False,
            "external_write": False,
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

    @staticmethod
    def _confidence(value: Any) -> Decimal:
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError) as exc:
            raise ValueError("confidence must be a decimal") from exc
        if not parsed.is_finite() or parsed <= 0 or parsed > 1:
            raise ValueError("confidence must be greater than 0 and at most 1")
        return parsed

    @classmethod
    def _optional_text(
        cls,
        value: Any,
        field: str,
        max_length: int,
    ) -> str | None:
        if value is None or str(value).strip() == "":
            return None
        return cls._text(value, field, max_length)

    @classmethod
    def _signal_object(
        cls,
        value: Any,
        field: str,
        max_keys: int,
    ) -> dict[str, Any]:
        if value is None:
            return {}
        if not isinstance(value, dict) or len(value) > max_keys:
            raise ValueError(
                f"{field} must be an object with at most {max_keys} keys"
            )

        def normalize(item: Any, path: str, depth: int) -> Any:
            if depth > 4:
                raise ValueError(f"{path} exceeds maximum nesting depth")
            if item is None or isinstance(item, bool):
                return item
            if isinstance(item, int):
                return item
            if isinstance(item, float):
                parsed = Decimal(str(item))
                if not parsed.is_finite():
                    raise ValueError(f"{path} must be finite")
                return format(parsed, "f")
            if isinstance(item, Decimal):
                if not item.is_finite():
                    raise ValueError(f"{path} must be finite")
                return format(item, "f")
            if isinstance(item, str):
                return cls._text(item, path, 2000)
            if isinstance(item, list):
                if len(item) > 80:
                    raise ValueError(f"{path} contains too many values")
                return [
                    normalize(child, f"{path}[{index}]", depth + 1)
                    for index, child in enumerate(item)
                ]
            if isinstance(item, dict):
                if len(item) > 80:
                    raise ValueError(f"{path} contains too many keys")
                return {
                    cls._text(key, f"{path} key", 100): normalize(
                        child,
                        f"{path}.{key}",
                        depth + 1,
                    )
                    for key, child in sorted(
                        item.items(), key=lambda pair: str(pair[0])
                    )
                }
            raise ValueError(f"{path} contains an unsupported value")

        return normalize(value, field, 0)

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

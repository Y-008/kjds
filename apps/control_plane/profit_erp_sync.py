from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from urllib.parse import quote, urlparse

import httpx
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .action_policies import ActionAuthorizationService, require_action_authorization
from .batch_opportunity import BatchOpportunityCandidateRow, BatchOpportunityRunRow
from .domain import new_id
from .erpnext_poc import ErpNextPocProjector
from .sql_repository import Base

SYNC_CONTRACT_VERSION = "profit-erp-item-sync/1.0.0"
SYNC_STATES = frozenset(
    {
        "prepared",
        "blocked_connector_not_configured",
        "dispatching",
        "succeeded",
        "failed_write",
        "failed_readback",
    }
)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _text(value: Any, field: str, maximum: int = 200) -> str:
    normalized = str(value or "").strip()
    if not normalized or len(normalized) > maximum:
        raise ValueError(f"{field} must be 1 to {maximum} characters")
    return normalized


def _decimal(value: Any, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a decimal") from exc
    if not parsed.is_finite():
        raise ValueError(f"{field} must be finite")
    return parsed


class ProfitErpItemSyncRow(Base):
    __tablename__ = "profit_erp_item_syncs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_ref",
            "store_ref",
            "idempotency_key",
            name="uq_profit_erp_item_sync_idempotency",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_ref: Mapped[str] = mapped_column(String, nullable=False)
    store_ref: Mapped[str] = mapped_column(String, nullable=False)
    run_id: Mapped[str] = mapped_column(ForeignKey("batch_opportunity_runs.id"), nullable=False)
    candidate_id: Mapped[str] = mapped_column(ForeignKey("batch_opportunity_candidates.id"), nullable=False)
    product_id: Mapped[str] = mapped_column(String, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    evidence_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    remote_name: Mapped[str | None] = mapped_column(String, nullable=True)
    readback_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    readback_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ErpItemConnector(Protocol):
    @property
    def configured(self) -> bool: ...

    def write_draft_and_readback(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class DisabledErpItemConnector:
    configured = False

    def write_draft_and_readback(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("ERPNext Item connector is not configured")


class FrappeErpItemConnector:
    """Minimal Frappe REST adapter: Item draft create/read only."""

    CREATE_ENDPOINT = "/api/resource/Item"
    READ_ENDPOINT = "/api/resource/Item/{item_code}"

    def __init__(self, *, base_url: str, api_key: str, api_secret: str, timeout_seconds: float = 15) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "erpnext"}:
            raise ValueError("ERPNext base URL must use HTTPS outside a local sidecar")
        self.base_url = base_url.rstrip("/")
        self.api_key = _text(api_key, "ERPNext API key", 500)
        self.api_secret = _text(api_secret, "ERPNext API secret", 500)
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return True

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"token {self.api_key}:{self.api_secret}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def write_draft_and_readback(self, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("docstatus") != 0 or payload.get("opening_stock", 0) != 0:
            raise ValueError("ERP Item sync only permits a zero-stock draft")
        item_code = quote(_text(payload.get("item_code"), "item_code", 140), safe="")
        resource = f"{self.base_url}{self.CREATE_ENDPOINT}"
        item_resource = f"{self.base_url}{self.READ_ENDPOINT.format(item_code=item_code)}"
        with httpx.Client(timeout=self.timeout_seconds, follow_redirects=False) as client:
            existing = client.get(item_resource, headers=self._headers())
            if existing.status_code == 404:
                written = client.post(resource, headers=self._headers(), json=payload)
                written.raise_for_status()
            elif existing.is_success:
                current = existing.json().get("data", {})
                if str(current.get("custom_kjds_product_id") or "") != str(payload["custom_kjds_product_id"]):
                    raise RuntimeError("ERPNext Item code already belongs to a different KJDS product")
            else:
                existing.raise_for_status()
            readback = client.get(item_resource, headers=self._headers())
            readback.raise_for_status()
            return dict(readback.json().get("data") or {})


def connector_from_environment() -> ErpItemConnector:
    base_url = os.getenv("KJDS_ERPNEXT_BASE_URL", "").strip()
    api_key = os.getenv("KJDS_ERPNEXT_API_KEY", "").strip()
    api_secret = os.getenv("KJDS_ERPNEXT_API_SECRET", "").strip()
    if not (base_url and api_key and api_secret):
        return DisabledErpItemConnector()
    return FrappeErpItemConnector(base_url=base_url, api_key=api_key, api_secret=api_secret)


class ProfitQualifiedErpSync:
    """Deep seam from authoritative profitable candidate to ERP Item draft."""

    def __init__(
        self,
        *,
        engine,
        evidence,
        repository,
        connector: ErpItemConnector | None = None,
        action_authorization: ActionAuthorizationService | None = None,
    ) -> None:
        self.engine = engine
        self.evidence = evidence
        self.repository = repository
        self.connector = connector or DisabledErpItemConnector()
        self.action_authorization = action_authorization or ActionAuthorizationService()
        self.projector = ErpNextPocProjector()

    def workspace(self, *, tenant_ref: str, store_ref: str) -> dict[str, Any]:
        tenant = _text(tenant_ref, "tenant_ref", 160)
        store = _text(store_ref, "store_ref", 160)
        with Session(self.engine) as session:
            run = session.scalar(
                select(BatchOpportunityRunRow)
                .where(BatchOpportunityRunRow.store_ref == store)
                .order_by(BatchOpportunityRunRow.as_of.desc(), BatchOpportunityRunRow.id.desc())
                .limit(1)
            )
            candidates = [] if run is None else list(
                session.scalars(
                    select(BatchOpportunityCandidateRow)
                    .where(BatchOpportunityCandidateRow.run_id == run.id)
                    .order_by(BatchOpportunityCandidateRow.rank)
                )
            )
            rows = list(
                session.scalars(
                    select(ProfitErpItemSyncRow)
                    .where(
                        ProfitErpItemSyncRow.tenant_ref == tenant,
                        ProfitErpItemSyncRow.store_ref == store,
                    )
                    .order_by(ProfitErpItemSyncRow.created_at.desc())
                    .limit(200)
                )
            )
        qualified: list[BatchOpportunityCandidateRow] = []
        if run is not None:
            for candidate in candidates:
                if self._qualification_blockers(candidate.payload_json, run):
                    continue
                try:
                    self.evidence.require_valid(
                        sorted(
                            set(
                                [
                                    run.evidence_id,
                                    candidate.evidence_id,
                                    *candidate.payload_json.get("evidence_ids", []),
                                ]
                            )
                        )
                    )
                except (KeyError, RuntimeError, ValueError):
                    continue
                qualified.append(candidate)
        return {
            "contract_version": SYNC_CONTRACT_VERSION,
            "state": "ready" if qualified else "no_data",
            "tenant_ref": tenant,
            "store_ref": store,
            "latest_run_id": run.id if run else None,
            "counts": {
                "evaluated_candidates": len(candidates),
                "profit_qualified": len(qualified),
                "sync_records": len(rows),
                "succeeded": sum(row.status == "succeeded" for row in rows),
            },
            "connector": {"configured": self.connector.configured, "write_scope": "Item draft create/read only"},
            "external_effects": {
                "opening_stock": 0,
                "purchase_order_created": False,
                "payment_created": False,
                "ozon_write_performed": False,
            },
            "blockers": [] if qualified else ["no_profit_qualified_candidate"],
            "eligible_items": [
                {
                    "run_id": run.id,
                    "candidate_id": candidate.id,
                    "product_id": candidate.payload_json["canonical_product_id"],
                    "downside_cm3_cny": candidate.payload_json["economics"]["downside"]["cm3_cny"],
                    "candidate_key": candidate.candidate_key,
                }
                for candidate in qualified
            ],
            "owner": "commerce_finance",
            "sla_hours": 24,
            "next": "补齐 checkout、税、目标仓运费与十五项悲观 CM3" if not qualified else "选择利润款建立 ERP Item 草稿同步",
            "syncs": [self._view(row) for row in rows],
        }

    def prepare(
        self,
        *,
        tenant_ref: str,
        store_ref: str,
        run_id: str,
        candidate_id: str,
        idempotency_key: str,
        actor_id: str,
    ) -> dict[str, Any]:
        tenant = _text(tenant_ref, "tenant_ref", 160)
        store = _text(store_ref, "store_ref", 160)
        run_ref = _text(run_id, "run_id", 160)
        candidate_ref = _text(candidate_id, "candidate_id", 160)
        key = _text(idempotency_key, "idempotency_key", 160)
        actor = _text(actor_id, "actor_id", 160)
        require_action_authorization(
            self.action_authorization,
            self.repository,
            action="erp_item_draft_sync",
            subject_id=candidate_ref,
            actor_id=actor,
            occurred_at=datetime.now(UTC),
            phase="request",
        )
        request_hash = _sha256({"tenant_ref": tenant, "store_ref": store, "run_id": run_ref, "candidate_id": candidate_ref})
        now = datetime.now(UTC)
        with Session(self.engine) as session, session.begin():
            existing = session.scalar(
                select(ProfitErpItemSyncRow).where(
                    ProfitErpItemSyncRow.tenant_ref == tenant,
                    ProfitErpItemSyncRow.store_ref == store,
                    ProfitErpItemSyncRow.idempotency_key == key,
                )
            )
            if existing is not None:
                if existing.request_sha256 != request_hash:
                    raise ValueError("ERP Item sync idempotency conflict")
                return self._view(existing)
            run = session.get(BatchOpportunityRunRow, run_ref)
            candidate = session.get(BatchOpportunityCandidateRow, candidate_ref)
            if run is None or run.store_ref != store:
                raise KeyError("Batch opportunity run not found in authorized store")
            if candidate is None or candidate.run_id != run.id:
                raise KeyError("Batch opportunity candidate not found in run")
            blockers = self._qualification_blockers(candidate.payload_json, run)
            if blockers:
                raise ValueError("Candidate is not profit-qualified: " + ",".join(blockers))
            product_id = str(candidate.payload_json.get("canonical_product_id") or "").strip()
            product = self.repository.get_product(product_id)
            evidence_ids = sorted(set([run.evidence_id, candidate.evidence_id, *candidate.payload_json.get("evidence_ids", [])]))
            self.evidence.require_valid(evidence_ids)
            projection = self.projector.project_item(
                product_id=product.id,
                version=1,
                sku=product.sku,
                name=product.name,
                stock_uom="Nos",
                evidence_ids=evidence_ids,
            )
            payload = {**projection.payload, "opening_stock": 0}
            payload_hash = _sha256(payload)
            status = "prepared" if self.connector.configured else "blocked_connector_not_configured"
            row = ProfitErpItemSyncRow(
                id=new_id("ers"), tenant_ref=tenant, store_ref=store, run_id=run.id,
                candidate_id=candidate.id, product_id=product.id, idempotency_key=key,
                request_sha256=request_hash, payload_sha256=payload_hash, payload_json=payload,
                evidence_ids_json=evidence_ids, status=status, attempts=0, remote_name=None,
                readback_sha256=None, readback_json=None, last_error=None, created_by=actor,
                created_at=now, updated_at=now,
            )
            session.add(row)
            session.flush()
            return self._view(row)

    def dispatch(
        self,
        *,
        sync_id: str,
        tenant_ref: str,
        store_ref: str,
        actor_id: str,
    ) -> dict[str, Any]:
        if not self.connector.configured:
            raise ValueError("ERPNext Item connector is not configured")
        with Session(self.engine) as session, session.begin():
            row = session.get(ProfitErpItemSyncRow, _text(sync_id, "sync_id", 160))
            if row is None or row.tenant_ref != tenant_ref or row.store_ref != store_ref:
                raise KeyError("ERP Item sync not found in authorized scope")
            if row.status == "succeeded":
                return self._view(row)
            run = session.get(BatchOpportunityRunRow, row.run_id)
            candidate = session.get(BatchOpportunityCandidateRow, row.candidate_id)
            if run is None or candidate is None or self._qualification_blockers(candidate.payload_json, run):
                raise ValueError("ERP Item sync source is no longer qualified")
            evidence_ids = sorted(
                set([run.evidence_id, candidate.evidence_id, *candidate.payload_json.get("evidence_ids", [])])
            )
            self.evidence.require_valid(evidence_ids)
            if _sha256(row.payload_json) != row.payload_sha256:
                raise ValueError("ERP Item sync payload integrity check failed")
            require_action_authorization(
                self.action_authorization,
                self.repository,
                action="erp_item_draft_sync",
                subject_id=row.id,
                actor_id=_text(actor_id, "actor_id", 160),
                occurred_at=datetime.now(UTC),
                phase="execute",
                executor_id="erpnext-item-adapter",
            )
            row.status = "dispatching"
            row.attempts += 1
            row.updated_at = datetime.now(UTC)
            payload = dict(row.payload_json)
        try:
            readback = self.connector.write_draft_and_readback(payload)
        except Exception as exc:
            with Session(self.engine) as session, session.begin():
                row = session.get(ProfitErpItemSyncRow, sync_id)
                row.status = "failed_write"
                row.last_error = str(exc)[:500]
                row.updated_at = datetime.now(UTC)
                result = self._view(row)
            return result
        expected = {
            "item_code": payload["item_code"],
            "docstatus": 0,
            "custom_kjds_product_id": payload["custom_kjds_product_id"],
        }
        actual = {key: readback.get(key) for key in expected}
        with Session(self.engine) as session, session.begin():
            row = session.get(ProfitErpItemSyncRow, sync_id)
            row.readback_json = readback
            row.readback_sha256 = _sha256(readback)
            row.remote_name = str(readback.get("name") or readback.get("item_code") or "") or None
            row.status = "succeeded" if actual == expected else "failed_readback"
            row.last_error = None if actual == expected else "ERPNext Item readback mismatch"
            row.updated_at = datetime.now(UTC)
            return self._view(row)

    @staticmethod
    def _qualification_blockers(payload: dict[str, Any], run: BatchOpportunityRunRow) -> list[str]:
        blockers: list[str] = []
        economics = payload.get("economics") or {}
        downside = economics.get("downside") or {}
        if (payload.get("identity_match") or {}).get("status") != "exact":
            blockers.append("exact_identity_missing")
        if not payload.get("canonical_product_id"):
            blockers.append("canonical_product_binding_missing")
        if economics.get("cost_evidence_complete") is not True:
            blockers.append("fifteen_component_cost_evidence_incomplete")
        cm3 = downside.get("cm3_cny")
        floor = ((run.payload_json.get("limits") or {}).get("cm3_floor_cny", "0"))
        if cm3 is None or _decimal(cm3, "downside.cm3_cny") <= _decimal(floor, "cm3_floor_cny"):
            blockers.append("downside_cm3_not_above_floor")
        if downside.get("conservation_delta_cny") != "0.00":
            blockers.append("erosion_conservation_failed")
        if payload.get("invalid_evidence_ids"):
            blockers.append("invalid_evidence")
        return blockers

    @staticmethod
    def _view(row: ProfitErpItemSyncRow) -> dict[str, Any]:
        return {
            "contract_version": SYNC_CONTRACT_VERSION,
            "sync_id": row.id,
            "tenant_ref": row.tenant_ref,
            "store_ref": row.store_ref,
            "run_id": row.run_id,
            "candidate_id": row.candidate_id,
            "product_id": row.product_id,
            "status": row.status,
            "attempts": row.attempts,
            "payload_sha256": row.payload_sha256,
            "evidence_ids": list(row.evidence_ids_json),
            "remote_name": row.remote_name,
            "readback_sha256": row.readback_sha256,
            "last_error": row.last_error,
            "erp_item": {
                "item_code": row.payload_json["item_code"],
                "docstatus": 0,
                "opening_stock": 0,
            },
            "external_effects": {
                "purchase_order_created": False,
                "payment_created": False,
                "ozon_write_performed": False,
            },
        }

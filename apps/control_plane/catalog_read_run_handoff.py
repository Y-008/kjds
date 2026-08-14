from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    select,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .security import Principal
from .sql_repository import Base


class CatalogReadRunHandoffRow(Base):
    __tablename__ = "catalog_read_run_handoffs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "idempotency_key",
            name="uq_catalog_read_run_handoff_scoped_key",
        ),
        CheckConstraint(
            "length(tenant_ref) > 0 "
            "AND length(entity_ref) > 0 "
            "AND length(store_ref) > 0 "
            "AND length(scope_grant_authority_sha256) = 64 "
            "AND length(scope_evidence_authority_sha256) = 64 "
            "AND length(request_hash) = 64 "
            "AND json_type(scope_authority_json) = 'object' "
            "AND json_type(source_contract_json) = 'object'",
            name="ck_catalog_read_run_handoff_authority",
        ).ddl_if(dialect="sqlite"),
        CheckConstraint(
            "("
            "status = 'prepared' AND catalog_snapshot_id IS NULL "
            "AND catalog_snapshot_hash IS NULL AND error_code IS NULL "
            "AND completed_at IS NULL"
            ") OR ("
            "status = 'completed' AND catalog_snapshot_id IS NOT NULL "
            "AND length(catalog_snapshot_hash) = 64 "
            "AND error_code IS NULL AND completed_at IS NOT NULL"
            ") OR ("
            "status = 'blocked' AND catalog_snapshot_id IS NULL "
            "AND catalog_snapshot_hash IS NULL "
            "AND length(error_code) > 0 AND completed_at IS NOT NULL"
            ")",
            name="ck_catalog_read_run_handoff_state",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    tenant_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    entity_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    store_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    scope_grant_authority_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    scope_evidence_authority_sha256: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    scope_as_of: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    run_id: Mapped[str] = mapped_column(
        ForeignKey("read_only_pilot_runs.id"),
        nullable=False,
    )
    raw_response_evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_records.id"),
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_authority_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
    )
    source_contract_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    catalog_snapshot_id: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
    )
    catalog_snapshot_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    prepared_by: Mapped[str] = mapped_column(String(160), nullable=False)
    prepared_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class CatalogReadRunHandoffService:
    """Resume one verified official read response into the scoped Catalog."""

    CONTRACT_ID = "kjds-ozon-read-run-catalog-handoff-v1"

    def __init__(
        self,
        *,
        engine,
        pilot_runs,
        scoped_pilots,
        scoped_catalog,
        source_adapters,
        catalog,
    ) -> None:
        self.engine = engine
        self.pilot_runs = pilot_runs
        self.scoped_pilots = scoped_pilots
        self.scoped_catalog = scoped_catalog
        self.source_adapters = source_adapters
        self.catalog = catalog

    def import_run(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        run_id: str,
        idempotency_key: str,
        imported_by: str,
    ) -> dict[str, Any]:
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        run_ref = self._required(run_id, "read run id", 300)
        key = self._required(idempotency_key, "idempotency key", 160)
        actor = self._required(imported_by, "imported_by", 160)
        raw_evidence_id = self._verified_product_run(
            run_ref,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=context["cutoff"],
        )
        evidence_authority = self.scoped_catalog.require_import_evidence(
            evidence_ids=[raw_evidence_id],
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=context["cutoff"],
        )
        source_contract = self.source_adapters.catalog_contract(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=context["cutoff"],
            marketplace="ozon",
        )
        scope_authority = {
            **context["scope"],
            "scope_evidence_authority_sha256": evidence_authority[
                "evidence_authority_sha256"
            ],
            "scope_as_of": context["cutoff"].isoformat(),
        }
        request = {
            "tenant_ref": context["scope"]["tenant_ref"],
            "entity_ref": context["scope"]["entity_ref"],
            "store_ref": store_ref,
            "run_id": run_ref,
            "raw_response_evidence_id": raw_evidence_id,
            "idempotency_key": key,
            "scope_grant_authority_sha256": context["scope"][
                "scope_grant_authority_sha256"
            ],
            "scope_evidence_authority_sha256": evidence_authority[
                "evidence_authority_sha256"
            ],
            "adapter_registry_sha256": source_contract[
                "registry_sha256"
            ],
            "adapter_id": source_contract["adapter"]["adapter_id"],
            "adapter_version": source_contract["adapter"][
                "adapter_version"
            ],
        }
        row = self._prepare(
            request=request,
            scope_authority=scope_authority,
            source_contract=source_contract,
            actor=actor,
            cutoff=context["cutoff"],
        )
        if row["status"] != "prepared":
            return row
        frozen_scope, frozen_contract = self._frozen_authority(row["id"])
        authority_fields = (
            "tenant_ref",
            "entity_ref",
            "store_ref",
            "scope_grant_authority_sha256",
            "scope_evidence_authority_sha256",
        )
        if any(
            frozen_scope.get(field) != scope_authority.get(field)
            for field in authority_fields
        ):
            raise ValueError(
                "Prepared Catalog handoff scope authority is no longer current"
            )
        try:
            snapshot = self.catalog.import_ozon_evidence(
                evidence_ids=[raw_evidence_id],
                store_ref=store_ref,
                idempotency_key=f"read-run:{row['id']}",
                imported_by=actor,
                scope_authority=frozen_scope,
                source_contract=frozen_contract,
            )
        except ValueError:
            return self._block(
                row["id"],
                error_code="CATALOG_IMPORT_REJECTED",
            )
        return self._complete(
            row["id"],
            snapshot_id=snapshot["id"],
            snapshot_hash=snapshot["snapshot_hash"],
        )

    def list_scoped(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        limit: int = 100,
    ) -> dict[str, Any]:
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
            require_entity=False,
        )
        if context["scope"]["entity_ref"] is None:
            return self._empty(context)
        if limit < 1 or limit > 500:
            raise ValueError("Catalog handoff limit must be 1 to 500")
        with Session(self.engine) as session:
            rows = list(
                session.scalars(
                    select(CatalogReadRunHandoffRow)
                    .where(
                        CatalogReadRunHandoffRow.tenant_ref
                        == context["scope"]["tenant_ref"],
                        CatalogReadRunHandoffRow.entity_ref
                        == context["scope"]["entity_ref"],
                        CatalogReadRunHandoffRow.store_ref == store_ref,
                        CatalogReadRunHandoffRow.prepared_at
                        <= context["cutoff"],
                    )
                    .order_by(
                        CatalogReadRunHandoffRow.prepared_at.desc(),
                        CatalogReadRunHandoffRow.id,
                    )
                    .limit(limit)
                )
            )
        items = [self._serialize(row) for row in rows]
        return self._collection(context=context, items=items)

    def get_scoped(
        self,
        *,
        handoff_id: str,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        with Session(self.engine) as session:
            row = session.scalar(
                select(CatalogReadRunHandoffRow).where(
                    CatalogReadRunHandoffRow.id == handoff_id,
                    CatalogReadRunHandoffRow.tenant_ref
                    == context["scope"]["tenant_ref"],
                    CatalogReadRunHandoffRow.entity_ref
                    == context["scope"]["entity_ref"],
                    CatalogReadRunHandoffRow.store_ref == store_ref,
                    CatalogReadRunHandoffRow.prepared_at
                    <= context["cutoff"],
                )
            )
        if row is None:
            raise KeyError(
                "Catalog read-run handoff not found in authorized scope"
            )
        return self._serialize(row)

    def _verified_product_run(
        self,
        run_id: str,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> str:
        run = self.scoped_pilots.require_run(
            run_id,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        evidence_id = run.get("raw_response_evidence_id")
        if (
            run.get("operation") != "ozon.product.read"
            or run.get("status") != "completed"
            or run.get("outcome") != "succeeded"
            or run.get("raw_response_stored") is not True
            or run.get("raw_response_verified") is not True
            or not isinstance(evidence_id, str)
            or not evidence_id
        ):
            raise ValueError(
                "Catalog handoff requires one verified successful "
                "Ozon product read response"
            )
        self.pilot_runs.verified_product_response_bundle(evidence_id)
        return evidence_id

    def _prepare(
        self,
        *,
        request: dict[str, Any],
        scope_authority: dict[str, Any],
        source_contract: dict[str, Any],
        actor: str,
        cutoff: datetime,
    ) -> dict[str, Any]:
        request_hash = self._hash(request)
        query = select(CatalogReadRunHandoffRow).where(
            CatalogReadRunHandoffRow.tenant_ref
            == request["tenant_ref"],
            CatalogReadRunHandoffRow.entity_ref
            == request["entity_ref"],
            CatalogReadRunHandoffRow.store_ref == request["store_ref"],
            CatalogReadRunHandoffRow.idempotency_key
            == request["idempotency_key"],
        )
        with Session(self.engine) as session:
            existing = session.scalar(query)
            if existing is not None:
                self._same_request(existing, request_hash)
                return self._serialize(existing)
        try:
            with Session(self.engine) as session, session.begin():
                row = CatalogReadRunHandoffRow(
                    id=new_id("crh"),
                    tenant_ref=request["tenant_ref"],
                    entity_ref=request["entity_ref"],
                    store_ref=request["store_ref"],
                    scope_grant_authority_sha256=request[
                        "scope_grant_authority_sha256"
                    ],
                    scope_evidence_authority_sha256=request[
                        "scope_evidence_authority_sha256"
                    ],
                    scope_as_of=cutoff,
                    run_id=request["run_id"],
                    raw_response_evidence_id=request[
                        "raw_response_evidence_id"
                    ],
                    idempotency_key=request["idempotency_key"],
                    request_hash=request_hash,
                    scope_authority_json=scope_authority,
                    source_contract_json=source_contract,
                    status="prepared",
                    catalog_snapshot_id=None,
                    catalog_snapshot_hash=None,
                    error_code=None,
                    prepared_by=actor,
                    prepared_at=datetime.now(UTC),
                    completed_at=None,
                )
                session.add(row)
                session.flush()
                handoff_id = row.id
        except IntegrityError:
            with Session(self.engine) as session:
                existing = session.scalar(query)
                if existing is None:
                    raise
                self._same_request(existing, request_hash)
                return self._serialize(existing)
        return self._get(handoff_id)

    def _complete(
        self,
        handoff_id: str,
        *,
        snapshot_id: str,
        snapshot_hash: str,
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            row = self._row(session, handoff_id, lock=True)
            if row.status == "completed":
                if (
                    row.catalog_snapshot_id != snapshot_id
                    or row.catalog_snapshot_hash != snapshot_hash
                ):
                    raise ValueError(
                        "Completed Catalog handoff is immutable"
                    )
                return self._serialize(row)
            if row.status != "prepared":
                return self._serialize(row)
            row.status = "completed"
            row.catalog_snapshot_id = snapshot_id
            row.catalog_snapshot_hash = self._sha256(
                snapshot_hash,
                "catalog snapshot hash",
            )
            row.completed_at = datetime.now(UTC)
        return self._get(handoff_id)

    def _block(self, handoff_id: str, *, error_code: str) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            row = self._row(session, handoff_id, lock=True)
            if row.status != "prepared":
                return self._serialize(row)
            row.status = "blocked"
            row.error_code = self._required(
                error_code,
                "error code",
                80,
            )
            row.completed_at = datetime.now(UTC)
        return self._get(handoff_id)

    def _get(self, handoff_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            return self._serialize(self._row(session, handoff_id))

    def _frozen_authority(
        self,
        handoff_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        with Session(self.engine) as session:
            row = self._row(session, handoff_id)
            return (
                dict(row.scope_authority_json),
                dict(row.source_contract_json),
            )

    @staticmethod
    def _same_request(
        row: CatalogReadRunHandoffRow,
        request_hash: str,
    ) -> None:
        if row.request_hash != request_hash:
            raise ValueError(
                "Catalog handoff idempotency conflict; changed run, "
                "scope, Evidence or adapter requires a new key"
            )

    @staticmethod
    def _row(
        session: Session,
        handoff_id: str,
        *,
        lock: bool = False,
    ) -> CatalogReadRunHandoffRow:
        row = session.get(
            CatalogReadRunHandoffRow,
            handoff_id,
            with_for_update=lock,
        )
        if row is None:
            raise KeyError(f"Catalog handoff not found: {handoff_id}")
        return row

    def _serialize(
        self,
        row: CatalogReadRunHandoffRow,
    ) -> dict[str, Any]:
        contract = (
            row.source_contract_json
            if isinstance(row.source_contract_json, dict)
            else {}
        )
        adapter = (
            contract.get("adapter", {})
            if isinstance(contract.get("adapter"), dict)
            else {}
        )
        payload = {
            "contract_id": self.CONTRACT_ID,
            "id": row.id,
            "status": row.status,
            "scope": {
                "tenant_ref": row.tenant_ref,
                "entity_ref": row.entity_ref,
                "store_ref": row.store_ref,
                "scope_grant_authority_sha256": (
                    row.scope_grant_authority_sha256
                ),
                "scope_evidence_authority_sha256": (
                    row.scope_evidence_authority_sha256
                ),
                "as_of": self._iso(row.scope_as_of),
            },
            "run_id": row.run_id,
            "raw_response_evidence_id": row.raw_response_evidence_id,
            "idempotency_key": row.idempotency_key,
            "request_hash": row.request_hash,
            "source_adapter": {
                "adapter_id": adapter.get("adapter_id"),
                "adapter_version": adapter.get("adapter_version"),
                "adapter_contract_sha256": contract.get(
                    "adapter_contract_sha256"
                ),
                "source_grade": adapter.get("max_source_grade"),
                "semantic_authority": adapter.get(
                    "semantic_authority"
                ),
            },
            "catalog_snapshot_id": row.catalog_snapshot_id,
            "catalog_snapshot_hash": row.catalog_snapshot_hash,
            "error_code": row.error_code,
            "prepared_by": row.prepared_by,
            "prepared_at": self._iso(row.prepared_at),
            "completed_at": (
                self._iso(row.completed_at)
                if row.completed_at is not None
                else None
            ),
            "external_write_allowed": False,
            "automatic_product_binding": False,
            "approval_created": False,
            "permit_created": False,
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def _collection(
        self,
        *,
        context: dict[str, Any],
        items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload = {
            "contract_id": self.CONTRACT_ID,
            "status": "ready" if items else "no_data",
            "as_of": context["cutoff"].isoformat(),
            "scope": context["scope"],
            "items": items,
            "counts": {
                "total": len(items),
                "prepared": sum(
                    item["status"] == "prepared" for item in items
                ),
                "completed": sum(
                    item["status"] == "completed" for item in items
                ),
                "blocked": sum(
                    item["status"] == "blocked" for item in items
                ),
            },
            "source_gaps": [] if items else ["catalog_handoff_not_available"],
            "external_write_allowed": False,
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def _empty(self, context: dict[str, Any]) -> dict[str, Any]:
        payload = self._collection(context=context, items=[])
        payload["status"] = context["status"]
        payload["source_gaps"] = [
            context.get("reason", "entity_scope_authority_missing")
        ]
        payload["snapshot_sha256"] = self._hash(
            {
                key: value
                for key, value in payload.items()
                if key != "snapshot_sha256"
            }
        )
        return payload

    @staticmethod
    def _context(
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        require_entity: bool = True,
    ) -> dict[str, Any]:
        if as_of.tzinfo is None:
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
        if require_entity and not ready:
            raise ValueError(
                "Catalog handoff requires one current entity scope grant"
            )
        cutoff = as_of.astimezone(UTC)
        return {
            "status": (
                "ready"
                if ready
                else "blocked"
                if entity_scope.get("status") == "blocked"
                else "no_data"
            ),
            "reason": (
                None
                if ready
                else entity_scope.get(
                    "reason",
                    "entity_scope_authority_missing",
                )
            ),
            "cutoff": cutoff,
            "scope": {
                "tenant_ref": principal.tenant_ref,
                "entity_ref": (
                    str(entity_scope["entity_ref"]) if ready else None
                ),
                "store_ref": store_ref,
                "scope_grant_authority_sha256": (
                    str(entity_scope["authority_sha256"])
                    if ready
                    else None
                ),
            },
        }

    @staticmethod
    def _required(value: Any, field: str, maximum: int) -> str:
        normalized = str(value or "").strip()
        if not normalized or len(normalized) > maximum:
            raise ValueError(f"Catalog handoff requires valid {field}")
        return normalized

    @staticmethod
    def _sha256(value: Any, field: str) -> str:
        normalized = str(value or "").strip()
        if (
            len(normalized) != 64
            or any(
                character not in "0123456789abcdef"
                for character in normalized
            )
        ):
            raise ValueError(f"Catalog handoff {field} must be SHA-256")
        return normalized

    @staticmethod
    def _iso(value: datetime) -> str:
        return (
            value.replace(tzinfo=UTC)
            if value.tzinfo is None
            else value.astimezone(UTC)
        ).isoformat()

    @staticmethod
    def _hash(value: Any) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode()
        ).hexdigest()

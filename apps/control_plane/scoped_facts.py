from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .domain import new_id
from .evidence import LineageEdgeRow
from .facts import FactRecordRow, PromotionRunRow
from .imports import ImportDataRow, ImportJobRow
from .ozon_contracts import (
    CONTRACT_VERSION,
    OzonRecordType,
    natural_key,
    normalize_record,
)
from .security import Principal
from .sql_repository import ProductRow


class ScopedFactPromotionAuthority:
    """Promote one native scoped Ozon import into formal internal Facts."""

    CONTRACT_ID = "kjds-native-scoped-formal-facts-v1"
    FINANCE_TYPES = frozenset(
        {
            OzonRecordType.FEE.value,
            OzonRecordType.ACCRUAL.value,
            OzonRecordType.RETURN.value,
            OzonRecordType.SETTLEMENT.value,
        }
    )

    def __init__(
        self,
        *,
        engine,
        scoped_imports,
        scoped_evidence,
        finance_review_validator: Callable[[str], None] | None = None,
        fee_mapping_validator: Callable[[str], None] | None = None,
        accrual_classification_validator: Callable[[str], None] | None = None,
    ) -> None:
        self.engine = engine
        self.scoped_imports = scoped_imports
        self.scoped_evidence = scoped_evidence
        self.finance_review_validator = finance_review_validator
        self.fee_mapping_validator = fee_mapping_validator
        self.accrual_classification_validator = (
            accrual_classification_validator
        )

    def promote(
        self,
        import_id: str,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        created_by: str,
    ) -> dict[str, Any]:
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        imported = self.scoped_imports.require_import(
            import_id,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=context["cutoff"],
        )
        source_evidence_id = str(imported.get("evidence_id") or "").strip()
        source_evidence_sha256 = str(
            imported.get("scope", {}).get("source_evidence_sha256") or ""
        ).strip()
        review = self._require_source_review(
            evidence_id=source_evidence_id,
            expected_sha256=source_evidence_sha256,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=context["cutoff"],
        )
        self._require_finance_controls(
            import_id=import_id,
            record_type=str(imported["record_type"]),
        )
        request_sha256 = self._hash(
            {
                "contract_id": self.CONTRACT_ID,
                "contract_version": CONTRACT_VERSION,
                "import_id": import_id,
                "import_sha256": imported["sha256"],
                "source_evidence_id": source_evidence_id,
                "source_evidence_sha256": source_evidence_sha256,
                "scope": context["scope"],
                "source_review_authority_sha256": review[
                    "binding_authority_sha256"
                ],
            }
        )

        with (
            Session(self.engine, expire_on_commit=False) as session,
            session.begin(),
        ):
            job = session.scalar(
                select(ImportJobRow).where(
                    ImportJobRow.id == import_id,
                    ImportJobRow.tenant_ref
                    == context["scope"]["tenant_ref"],
                    ImportJobRow.entity_ref
                    == context["scope"]["entity_ref"],
                    ImportJobRow.store_ref
                    == context["scope"]["store_ref"],
                    ImportJobRow.scope_grant_authority_sha256
                    == context["scope"][
                        "scope_grant_authority_sha256"
                    ],
                    ImportJobRow.scope_as_of <= context["cutoff"],
                )
            )
            if job is None:
                raise KeyError(
                    "Ozon import not found in authorized Fact scope"
                )
            if (
                not job.evidence_id
                or job.evidence_id != source_evidence_id
                or job.source_evidence_sha256
                != source_evidence_sha256
            ):
                raise ValueError(
                    "Ozon import Evidence authority changed before promotion"
                )
            if job.status == "rejected":
                raise ValueError(
                    "Rejected import cannot be promoted to formal facts"
                )
            existing_run = session.scalar(
                select(PromotionRunRow).where(
                    PromotionRunRow.tenant_ref
                    == context["scope"]["tenant_ref"],
                    PromotionRunRow.entity_ref
                    == context["scope"]["entity_ref"],
                    PromotionRunRow.store_ref
                    == context["scope"]["store_ref"],
                    PromotionRunRow.request_sha256 == request_sha256,
                )
            )
            if existing_run is not None:
                return self._promotion_projection(
                    session=session,
                    row=existing_run,
                    idempotent=True,
                )

            prepared = self._prepare_rows(
                session=session,
                job=job,
                context=context,
            )
            now = datetime.now(UTC)
            promoted = 0
            duplicates = 0
            fact_ids: list[str] = []
            for item in prepared:
                existing = session.scalar(
                    select(FactRecordRow).where(
                        FactRecordRow.tenant_ref
                        == context["scope"]["tenant_ref"],
                        FactRecordRow.entity_ref
                        == context["scope"]["entity_ref"],
                        FactRecordRow.store_ref
                        == context["scope"]["store_ref"],
                        (
                            (
                                FactRecordRow.import_row_id
                                == item["row"].id
                            )
                            & (
                                FactRecordRow.contract_version
                                == CONTRACT_VERSION
                            )
                        )
                        | (
                            (
                                FactRecordRow.source
                                == job.source
                            )
                            & (
                                FactRecordRow.fact_type
                                == item["record_type"].value
                            )
                            & (
                                FactRecordRow.natural_key
                                == item["natural_key"]
                            )
                            & (
                                FactRecordRow.payload_hash
                                == item["payload_hash"]
                            )
                        ),
                    )
                )
                if existing is not None:
                    duplicates += 1
                    fact_ids.append(existing.id)
                    continue
                fact = FactRecordRow(
                    id=new_id("fact"),
                    source=job.source,
                    fact_type=item["record_type"].value,
                    natural_key=item["natural_key"],
                    contract_version=CONTRACT_VERSION,
                    payload_json=item["payload"],
                    payload_hash=item["payload_hash"],
                    effective_at=datetime.fromisoformat(
                        item["payload"]["effective_at"]
                    ),
                    recorded_at=now,
                    evidence_id=job.evidence_id,
                    import_row_id=item["row"].id,
                    product_id=item["product"].id,
                    resolution_status="resolved",
                    created_by=created_by,
                    tenant_ref=context["scope"]["tenant_ref"],
                    entity_ref=context["scope"]["entity_ref"],
                    store_ref=context["scope"]["store_ref"],
                    scope_grant_authority_sha256=context["scope"][
                        "scope_grant_authority_sha256"
                    ],
                    source_evidence_sha256=source_evidence_sha256,
                    scope_as_of=job.scope_as_of,
                )
                session.add(fact)
                session.add(
                    LineageEdgeRow(
                        id=new_id("lin"),
                        from_type="evidence",
                        from_id=job.evidence_id,
                        to_type="commerce_fact",
                        to_id=fact.id,
                        relationship="supports",
                        created_by=created_by,
                        recorded_at=now,
                    )
                )
                fact_ids.append(fact.id)
                promoted += 1

            run = PromotionRunRow(
                id=new_id("prom"),
                import_id=import_id,
                promoted_count=promoted,
                duplicate_count=duplicates,
                blocked_count=0,
                errors_json=[],
                created_by=created_by,
                created_at=now,
                tenant_ref=context["scope"]["tenant_ref"],
                entity_ref=context["scope"]["entity_ref"],
                store_ref=context["scope"]["store_ref"],
                scope_grant_authority_sha256=context["scope"][
                    "scope_grant_authority_sha256"
                ],
                source_evidence_sha256=source_evidence_sha256,
                scope_as_of=job.scope_as_of,
                request_sha256=request_sha256,
            )
            session.add(run)
            session.flush()
            result = self._promotion_projection(
                session=session,
                row=run,
                idempotent=False,
            )
            result["fact_ids"] = fact_ids
            return result

    def get(
        self,
        fact_id: str,
        *,
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
                select(FactRecordRow).where(
                    FactRecordRow.id == fact_id,
                    FactRecordRow.tenant_ref
                    == context["scope"]["tenant_ref"],
                    FactRecordRow.entity_ref
                    == context["scope"]["entity_ref"],
                    FactRecordRow.store_ref
                    == context["scope"]["store_ref"],
                    FactRecordRow.scope_grant_authority_sha256
                    == context["scope"][
                        "scope_grant_authority_sha256"
                    ],
                    FactRecordRow.scope_as_of <= context["cutoff"],
                    FactRecordRow.recorded_at <= context["cutoff"],
                )
            )
            if row is None:
                raise KeyError("Fact not found in authorized scope")
            return self._fact_projection(row)

    def list(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        fact_type: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        query = select(FactRecordRow).where(
            FactRecordRow.tenant_ref
            == context["scope"]["tenant_ref"],
            FactRecordRow.entity_ref
            == context["scope"]["entity_ref"],
            FactRecordRow.store_ref
            == context["scope"]["store_ref"],
            FactRecordRow.scope_grant_authority_sha256
            == context["scope"]["scope_grant_authority_sha256"],
            FactRecordRow.scope_as_of <= context["cutoff"],
            FactRecordRow.recorded_at <= context["cutoff"],
        )
        if fact_type:
            query = query.where(FactRecordRow.fact_type == fact_type)
        query = query.order_by(
            FactRecordRow.recorded_at.desc(),
            FactRecordRow.id,
        ).limit(min(max(limit, 1), 500))
        with Session(self.engine) as session:
            items = [
                self._fact_projection(row)
                for row in session.scalars(query).all()
            ]
        payload = {
            "contract_id": self.CONTRACT_ID,
            "status": "ready" if items else "no_data",
            "scope": context["scope"],
            "as_of": context["cutoff"].isoformat(),
            "items": items,
            "formal_fact_count": len(items),
            "legacy_rows_inferred": False,
            "claim_source_allowed": False,
            "accounting_posted": False,
            "external_write_allowed": False,
            "approval_created": False,
            "permit_created": False,
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def _prepare_rows(
        self,
        *,
        session: Session,
        job: ImportJobRow,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        rows = list(
            session.scalars(
                select(ImportDataRow)
                .where(ImportDataRow.import_id == job.id)
                .order_by(ImportDataRow.row_number)
            ).all()
        )
        if not rows:
            raise ValueError("Ozon import has no rows to promote")
        prepared: list[dict[str, Any]] = []
        for row in rows:
            if row.errors_json:
                raise ValueError(
                    f"Ozon import row {row.row_number} is rejected"
                )
            record_type = OzonRecordType(row.record_type)
            payload, errors = normalize_record(
                record_type,
                row.normalized_json,
            )
            if errors:
                raise ValueError(
                    f"Ozon import row {row.row_number} failed contract: "
                    + "; ".join(errors)
                )
            sku = str(payload.get("sku") or "").strip()
            if not sku:
                raise ValueError(
                    f"Ozon import row {row.row_number} requires exact SKU mapping"
                )
            products = list(
                session.scalars(
                    select(ProductRow).where(
                        ProductRow.sku == sku,
                        ProductRow.tenant_ref
                        == context["scope"]["tenant_ref"],
                        ProductRow.entity_ref
                        == context["scope"]["entity_ref"],
                        ProductRow.store_ref
                        == context["scope"]["store_ref"],
                        ProductRow.scope_grant_authority_sha256
                        == context["scope"][
                            "scope_grant_authority_sha256"
                        ],
                        ProductRow.scope_as_of <= job.scope_as_of,
                        ProductRow.created_at <= job.scope_as_of,
                    )
                ).all()
            )
            if len(products) != 1:
                raise ValueError(
                    f"Ozon import row {row.row_number} requires one exact "
                    "scoped Product/SKU mapping"
                )
            payload_hash = self._hash(payload)
            prepared.append(
                {
                    "row": row,
                    "record_type": record_type,
                    "payload": payload,
                    "payload_hash": payload_hash,
                    "natural_key": natural_key(record_type, payload),
                    "product": products[0],
                }
            )
        return prepared

    def _require_source_review(
        self,
        *,
        evidence_id: str,
        expected_sha256: str,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        if not evidence_id or len(expected_sha256) != 64:
            raise ValueError(
                "Native Fact promotion requires immutable source Evidence"
            )
        projection = self.scoped_evidence.project_targets(
            evidence_ids=[evidence_id],
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        targets = {
            item["evidence_id"]: item
            for item in projection.get("records", [])
            if item["evidence_id"] == evidence_id
        }
        target = targets.get(evidence_id)
        if (
            projection.get("status") != "ready"
            or projection.get("invalid_evidence_ids")
            or target is None
            or target.get("sha256") != expected_sha256
            or target.get("scope_binding", {}).get("status") != "ready"
            or not projection.get("binding_authority_sha256")
        ):
            raise ValueError(
                "Fact source Evidence lacks a current independent exact-scope review"
            )
        return projection

    def _require_finance_controls(
        self,
        *,
        import_id: str,
        record_type: str,
    ) -> None:
        if record_type not in self.FINANCE_TYPES:
            return
        if self.finance_review_validator is None:
            raise ValueError(
                "Finance import requires an independent accepted source review"
            )
        self.finance_review_validator(import_id)
        if record_type == OzonRecordType.FEE.value:
            if self.fee_mapping_validator is None:
                raise ValueError(
                    "Ozon fee import requires approved fee mappings"
                )
            self.fee_mapping_validator(import_id)
        if record_type == OzonRecordType.ACCRUAL.value:
            if self.accrual_classification_validator is None:
                raise ValueError(
                    "Ozon accrual import requires approved classifications"
                )
            self.accrual_classification_validator(import_id)

    def _promotion_projection(
        self,
        *,
        session: Session,
        row: PromotionRunRow,
        idempotent: bool,
    ) -> dict[str, Any]:
        fact_ids = list(
            session.scalars(
                select(FactRecordRow.id)
                .join(
                    ImportDataRow,
                    FactRecordRow.import_row_id == ImportDataRow.id,
                )
                .where(
                    ImportDataRow.import_id == row.import_id,
                    FactRecordRow.tenant_ref == row.tenant_ref,
                    FactRecordRow.entity_ref == row.entity_ref,
                    FactRecordRow.store_ref == row.store_ref,
                )
                .order_by(FactRecordRow.id)
            ).all()
        )
        payload = {
            "contract_id": self.CONTRACT_ID,
            "id": row.id,
            "import_id": row.import_id,
            "promoted_count": row.promoted_count,
            "duplicate_count": row.duplicate_count,
            "blocked_count": row.blocked_count,
            "errors": row.errors_json,
            "created_by": row.created_by,
            "created_at": self._iso(row.created_at),
            "scope": {
                "tenant_ref": row.tenant_ref,
                "entity_ref": row.entity_ref,
                "store_ref": row.store_ref,
                "scope_grant_authority_sha256": (
                    row.scope_grant_authority_sha256
                ),
                "source_evidence_sha256": row.source_evidence_sha256,
                "scope_as_of": self._iso(row.scope_as_of),
            },
            "request_sha256": row.request_sha256,
            "fact_ids": fact_ids,
            "idempotent": idempotent,
            "formal_fact_promotion_allowed": True,
            "accounting_posted": False,
            "claim_source_allowed": False,
            "external_write_allowed": False,
            "approval_created": False,
            "permit_created": False,
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    @classmethod
    def _fact_projection(cls, row: FactRecordRow) -> dict[str, Any]:
        payload = {
            "contract_id": cls.CONTRACT_ID,
            "id": row.id,
            "source": row.source,
            "fact_type": row.fact_type,
            "natural_key": row.natural_key,
            "contract_version": row.contract_version,
            "payload": row.payload_json,
            "payload_hash": row.payload_hash,
            "effective_at": cls._iso(row.effective_at),
            "recorded_at": cls._iso(row.recorded_at),
            "evidence_id": row.evidence_id,
            "import_row_id": row.import_row_id,
            "product_id": row.product_id,
            "resolution_status": row.resolution_status,
            "created_by": row.created_by,
            "scope": {
                "tenant_ref": row.tenant_ref,
                "entity_ref": row.entity_ref,
                "store_ref": row.store_ref,
                "scope_grant_authority_sha256": (
                    row.scope_grant_authority_sha256
                ),
                "source_evidence_sha256": row.source_evidence_sha256,
                "scope_as_of": cls._iso(row.scope_as_of),
            },
            "formal_fact": True,
            "accounting_posted": False,
            "claim_source_allowed": False,
            "external_write_allowed": False,
            "approval_created": False,
            "permit_created": False,
        }
        payload["snapshot_sha256"] = cls._hash(payload)
        return payload

    @staticmethod
    def _context(
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        if as_of.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        cutoff = as_of.astimezone(UTC)
        if cutoff > datetime.now(UTC):
            raise ValueError("as_of cannot be in the future")
        if not principal.can_access_store(store_ref):
            raise PermissionError(
                "Authenticated identity is not authorized for store_ref"
            )
        entity_ref = str(entity_scope.get("entity_ref") or "").strip()
        grant_hash = str(
            entity_scope.get("authority_sha256") or ""
        ).strip()
        if (
            entity_scope.get("status") != "ready"
            or not entity_ref
            or len(grant_hash) != 64
        ):
            raise ValueError(
                "Fact promotion requires one current entity scope grant"
            )
        return {
            "cutoff": cutoff,
            "scope": {
                "tenant_ref": principal.tenant_ref,
                "entity_ref": entity_ref,
                "store_ref": store_ref,
                "scope_grant_authority_sha256": grant_hash,
            },
        }

    @staticmethod
    def _iso(value: datetime | None) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat()

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

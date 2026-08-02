from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .evidence import EvidenceGrade
from .imports import ImportJobRow
from .security import Principal


class ScopedOzonImportAuthority:
    """Authorize immutable Ozon export staging in one native scope."""

    CONTRACT_ID = "kjds-scoped-ozon-import-staging-v1"

    def __init__(self, *, engine, imports, evidence) -> None:
        self.engine = engine
        self.imports = imports
        self.evidence = evidence

    def find_by_content(
        self,
        content: bytes,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any] | None:
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
            require_entity=True,
        )
        existing = self.imports.find_by_content(
            content,
            scope_authority={
                **context["scope"],
                "source_evidence_sha256": hashlib.sha256(
                    content
                ).hexdigest(),
                "scope_as_of": context["cutoff"].isoformat(),
            },
        )
        if existing is None:
            return None
        if (
            existing.scope is None
            or existing.scope["scope_grant_authority_sha256"]
            != context["scope"]["scope_grant_authority_sha256"]
        ):
            raise ValueError(
                "Ozon import grant authority changed; reauthorization is required"
            )
        self._require_source_evidence(
            evidence_id=existing.evidence_id,
            expected_sha256=existing.sha256,
            as_of=context["cutoff"],
        )
        return self._project(existing)

    def import_file(
        self,
        *,
        filename: str,
        content: bytes,
        evidence_id: str,
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
            require_entity=True,
        )
        source_hash = hashlib.sha256(content).hexdigest()
        self._require_source_evidence(
            evidence_id=evidence_id,
            expected_sha256=source_hash,
            as_of=context["cutoff"],
        )
        result = self.imports.import_file(
            filename=filename,
            content=content,
            evidence_id=evidence_id,
            scope_authority={
                **context["scope"],
                "source_evidence_sha256": source_hash,
                "scope_as_of": context["cutoff"].isoformat(),
            },
        )
        return self._project(result)

    def get(
        self,
        import_id: str,
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
            require_entity=True,
        )
        with Session(self.engine) as session:
            found = session.scalar(
                select(ImportJobRow.id).where(
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
        if found is None:
            raise KeyError("Ozon import not found in authorized scope")
        result = self.imports.get(import_id)
        self._require_source_evidence(
            evidence_id=result.evidence_id,
            expected_sha256=result.sha256,
            as_of=context["cutoff"],
        )
        return self._project(result)

    def list(
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
        if context["status"] != "ready":
            return self._collection(context=context, items=[])
        if limit < 1 or limit > 500:
            raise ValueError("Ozon import limit must be 1 to 500")
        with Session(self.engine) as session:
            ids = list(
                session.scalars(
                    select(ImportJobRow.id)
                    .where(
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
                    .order_by(
                        ImportJobRow.created_at.desc(),
                        ImportJobRow.id,
                    )
                    .limit(limit)
                )
            )
        items = []
        for import_id in ids:
            result = self.imports.get(import_id)
            self._require_source_evidence(
                evidence_id=result.evidence_id,
                expected_sha256=result.sha256,
                as_of=context["cutoff"],
            )
            items.append(self._project(result))
        return self._collection(context=context, items=items)

    def require_import(self, import_id: str, **values) -> dict[str, Any]:
        return self.get(import_id, **values)

    def _require_source_evidence(
        self,
        *,
        evidence_id: str | None,
        expected_sha256: str,
        as_of: datetime,
    ) -> None:
        if not evidence_id:
            raise ValueError("Native Ozon import requires source Evidence")
        self.evidence.require_current([evidence_id], as_of=as_of)
        record = self.evidence.get(evidence_id)
        verification = self.evidence.verify(evidence_id)
        if (
            not verification.valid
            or record.sha256 != expected_sha256
            or record.grade != EvidenceGrade.A
            or record.source != "ozon_export"
        ):
            raise ValueError(
                "Ozon import source Evidence is invalid or mismatched"
            )

    @classmethod
    def _project(cls, result) -> dict[str, Any]:
        payload = {
            **asdict(result),
            "contract_id": cls.CONTRACT_ID,
            "staging_status": "ready",
            "formal_fact_promotion_allowed": False,
            "accounting_posted": False,
            "product_mapping_performed": False,
            "external_write_allowed": False,
        }
        payload["snapshot_sha256"] = cls._hash(payload)
        return payload

    @classmethod
    def _collection(
        cls,
        *,
        context: dict[str, Any],
        items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload = {
            "contract_id": cls.CONTRACT_ID,
            "status": (
                "ready"
                if items
                else context["status"]
                if context["status"] != "ready"
                else "no_data"
            ),
            "as_of": context["cutoff"].isoformat(),
            "scope": context["scope"],
            "items": items,
            "counts": {
                "imports": len(items),
                "rows": sum(item["row_count"] for item in items),
                "accepted_rows": sum(
                    item["accepted_count"] for item in items
                ),
                "rejected_rows": sum(
                    item["rejected_count"] for item in items
                ),
            },
            "source_gaps": (
                []
                if items
                else [
                    context.get("reason")
                    or "scoped_ozon_import_not_available"
                ]
            ),
            "legacy_rows_inferred": False,
            "formal_fact_promotion_allowed": False,
            "external_write_allowed": False,
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
        require_entity: bool,
    ) -> dict[str, Any]:
        if as_of.tzinfo is None:
            raise ValueError("as_of must include a timezone")
        if not principal.can_access_store(store_ref):
            raise PermissionError(
                "Authenticated identity is not authorized for store_ref"
            )
        cutoff = as_of.astimezone(UTC)
        if cutoff > datetime.now(UTC):
            raise ValueError("as_of cannot be in the future")
        ready = (
            entity_scope.get("status") == "ready"
            and bool(entity_scope.get("entity_ref"))
            and bool(entity_scope.get("authority_sha256"))
        )
        if require_entity and not ready:
            raise ValueError(
                "Ozon import requires one current entity scope grant"
            )
        status = (
            "ready"
            if ready
            else "blocked"
            if entity_scope.get("status") == "blocked"
            else "no_data"
        )
        return {
            "status": status,
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

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .pilot_readiness import ReadOnlyPilotRow
from .pilot_runs import ReadOnlyPilotRunRow
from .read_only_claims import ReadOnlyClaimRow
from .security import Principal


class ScopedReadOnlyClaimAuthority:
    """Authorize reviewed Run interpretations in one native operating scope."""

    CONTRACT_ID = "kjds-scoped-read-only-claims-v1"
    STATUSES = {"pending_review", "accepted", "rejected"}

    def __init__(
        self,
        *,
        engine,
        claims,
        scoped_pilots,
        scoped_evidence,
    ) -> None:
        self.engine = engine
        self.claims = claims
        self.scoped_pilots = scoped_pilots
        self.scoped_evidence = scoped_evidence

    def propose(
        self,
        run_id: str,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        proposed_by: str,
        **values,
    ) -> dict[str, Any]:
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
            require_entity=True,
        )
        effective = self._datetime(values["effective_at"], "effective_at")
        if effective > context["cutoff"]:
            raise ValueError("Claim effective_at cannot be after as_of")
        run = self.scoped_pilots.require_run(
            run_id,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=context["cutoff"],
        )
        evidence_id = str(run.get("evidence_id") or "").strip()
        projection = self._require_evidence(
            evidence_id=evidence_id,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=context["cutoff"],
        )
        result = self.claims.propose(
            run_id,
            **values,
            proposed_by=proposed_by,
            scope_authority={
                **context["scope"],
                "scope_evidence_authority_sha256": projection[
                    "binding_authority_sha256"
                ],
                "scope_as_of": context["cutoff"].isoformat(),
            },
        )
        return self._project(
            result,
            context=context,
            evidence_projection=projection,
        )

    def list(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        run_id: str | None = None,
        status: str | None = None,
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
            raise ValueError("Read-only Claim limit must be 1 to 500")
        query = self._query(context)
        if run_id:
            query = query.where(ReadOnlyClaimRow.run_id == run_id)
        if status:
            normalized_status = status.strip().lower()
            if normalized_status not in self.STATUSES:
                raise ValueError("Unsupported read-only Claim status")
            query = query.where(ReadOnlyClaimRow.status == normalized_status)
        with Session(self.engine) as session:
            ids = list(
                session.scalars(
                    query.with_only_columns(ReadOnlyClaimRow.id)
                    .order_by(
                        ReadOnlyClaimRow.created_at.desc(),
                        ReadOnlyClaimRow.id,
                    )
                    .limit(limit)
                )
            )
        items = [
            self._project_current(
                self.claims.get(claim_id),
                context=context,
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
            )
            for claim_id in ids
        ]
        return self._collection(context=context, items=items)

    def get(
        self,
        claim_id: str,
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
        self._claim_id(claim_id, context=context)
        return self._project_current(
            self.claims.get(claim_id),
            context=context,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
        )

    def review(
        self,
        claim_id: str,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        reviewed_by: str,
        decision: str,
        rationale: str,
    ) -> dict[str, Any]:
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
            require_entity=True,
        )
        self._claim_id(claim_id, context=context)
        claim = self.claims.get(claim_id)
        self.scoped_pilots.require_run(
            claim["run_id"],
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=context["cutoff"],
        )
        projection = self._require_evidence(
            evidence_id=claim["evidence_id"],
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=context["cutoff"],
        )
        if (
            projection["binding_authority_sha256"]
            != claim["scope"]["scope_evidence_authority_sha256"]
        ):
            raise ValueError(
                "Read-only Claim Evidence authority changed; propose a new Claim"
            )
        result = self.claims.review(
            claim_id,
            decision=decision,
            rationale=rationale,
            reviewed_by=reviewed_by,
        )
        return self._project(
            result,
            context=context,
            evidence_projection=projection,
        )

    def _project_current(
        self,
        claim: dict[str, Any],
        *,
        context: dict[str, Any],
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
    ) -> dict[str, Any]:
        projection = self.scoped_evidence.project_targets(
            evidence_ids=[claim["evidence_id"]],
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=context["cutoff"],
        )
        return self._project(
            claim,
            context=context,
            evidence_projection=projection,
        )

    @staticmethod
    def _project(
        claim: dict[str, Any],
        *,
        context: dict[str, Any],
        evidence_projection: dict[str, Any],
    ) -> dict[str, Any]:
        current_authority = evidence_projection.get(
            "binding_authority_sha256"
        )
        frozen_authority = claim["scope"][
            "scope_evidence_authority_sha256"
        ]
        authority_ready = (
            evidence_projection.get("status") == "ready"
            and bool(current_authority)
            and current_authority == frozen_authority
        )
        return {
            **claim,
            "scope": {
                **claim["scope"],
                "current_grant_authority_sha256": context["scope"][
                    "scope_grant_authority_sha256"
                ],
            },
            "authority_status": "ready" if authority_ready else "blocked",
            "source_gaps": (
                []
                if authority_ready
                else sorted(
                    set(
                        evidence_projection.get("source_gaps", [])
                        or ["claim_evidence_authority_changed"]
                    )
                )
            ),
            "formal_fact_promoted": False,
            "external_write_allowed": False,
            "approval_created": False,
            "permit_created": False,
        }

    def _claim_id(
        self,
        claim_id: str,
        *,
        context: dict[str, Any],
    ) -> str:
        with Session(self.engine) as session:
            found = session.scalar(
                self._query(context)
                .where(ReadOnlyClaimRow.id == claim_id)
                .with_only_columns(ReadOnlyClaimRow.id)
            )
        if found is None:
            raise KeyError("Read-only Claim not found in authorized scope")
        return found

    @staticmethod
    def _query(context: dict[str, Any]):
        scope = context["scope"]
        return (
            select(ReadOnlyClaimRow)
            .join(
                ReadOnlyPilotRunRow,
                ReadOnlyPilotRunRow.id == ReadOnlyClaimRow.run_id,
            )
            .join(
                ReadOnlyPilotRow,
                ReadOnlyPilotRow.id == ReadOnlyPilotRunRow.pilot_id,
            )
            .where(
                ReadOnlyClaimRow.tenant_ref == scope["tenant_ref"],
                ReadOnlyClaimRow.entity_ref == scope["entity_ref"],
                ReadOnlyClaimRow.store_ref == scope["store_ref"],
                ReadOnlyClaimRow.scope_grant_authority_sha256
                == scope["scope_grant_authority_sha256"],
                ReadOnlyClaimRow.scope_as_of <= context["cutoff"],
                ReadOnlyClaimRow.created_at <= context["cutoff"],
                ReadOnlyPilotRow.tenant_ref == ReadOnlyClaimRow.tenant_ref,
                ReadOnlyPilotRow.entity_ref == ReadOnlyClaimRow.entity_ref,
                ReadOnlyPilotRow.store_ref == ReadOnlyClaimRow.store_ref,
                ReadOnlyPilotRow.scope_grant_authority_sha256
                == ReadOnlyClaimRow.scope_grant_authority_sha256,
                ReadOnlyPilotRow.scope_as_of <= context["cutoff"],
                ReadOnlyPilotRunRow.started_at <= context["cutoff"],
            )
        )

    def _require_evidence(
        self,
        *,
        evidence_id: str,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        if not evidence_id:
            raise ValueError(
                "Read-only Claim requires Run summary Evidence"
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
            for item in projection["records"]
            if item["evidence_id"] == evidence_id
        }
        if (
            projection["status"] != "ready"
            or projection["invalid_evidence_ids"]
            or evidence_id not in targets
            or targets[evidence_id]["scope_binding"]["status"] != "ready"
            or not projection["binding_authority_sha256"]
        ):
            raise ValueError(
                "Read-only Claim Evidence is not current and independently "
                "bound to the exact tenant/entity/store"
            )
        return projection

    def _collection(
        self,
        *,
        context: dict[str, Any],
        items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        blocked = sum(
            item.get("authority_status") != "ready" for item in items
        )
        status = (
            "partial"
            if blocked
            else "ready"
            if items
            else context["status"]
            if context["status"] != "ready"
            else "no_data"
        )
        source_gaps = sorted(
            {
                gap
                for item in items
                for gap in item.get("source_gaps", [])
            }
        )
        if not items:
            source_gaps = [
                context.get("reason")
                or "scoped_read_only_claim_not_available"
            ]
        payload = {
            "contract_id": self.CONTRACT_ID,
            "status": status,
            "as_of": context["cutoff"].isoformat(),
            "scope": context["scope"],
            "items": items,
            "counts": {
                "claims": len(items),
                "pending_review": sum(
                    item["status"] == "pending_review" for item in items
                ),
                "accepted": sum(
                    item["status"] == "accepted" for item in items
                ),
                "rejected": sum(
                    item["status"] == "rejected" for item in items
                ),
                "authority_blocked": blocked,
            },
            "source_gaps": source_gaps,
            "legacy_rows_inferred": False,
            "formal_fact_promoted": False,
            "external_write_allowed": False,
        }
        payload["snapshot_sha256"] = self._hash(payload)
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
                "Read-only Claim requires one current entity scope grant"
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
    def _datetime(value: str, name: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (AttributeError, ValueError) as exc:
            raise ValueError(f"{name} must be ISO-8601") from exc
        if parsed.tzinfo is None:
            raise ValueError(f"{name} must include timezone")
        return parsed.astimezone(UTC)

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

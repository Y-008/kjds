from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .pilot_readiness import ReadOnlyPilotRow
from .pilot_runs import ReadOnlyPilotRunRow
from .security import Principal


class ScopedReadOnlyPilotAuthority:
    """Authorize the existing Pilot/Run state machines in one native scope."""

    CONTRACT_ID = "kjds-scoped-read-only-pilots-v1"

    def __init__(
        self,
        *,
        engine,
        pilots,
        pilot_runs,
        scoped_evidence,
    ) -> None:
        self.engine = engine
        self.pilots = pilots
        self.pilot_runs = pilot_runs
        self.scoped_evidence = scoped_evidence

    def create(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        requested_by: str,
        **values,
    ) -> dict[str, Any]:
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
            require_entity=True,
        )
        evidence_ids = list(values.get("evidence_ids", []))
        projection = self._require_evidence(
            evidence_ids=evidence_ids,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=context["cutoff"],
        )
        result = self.pilots.create(
            **values,
            requested_by=requested_by,
            scope_authority={
                **context["scope"],
                "scope_evidence_authority_sha256": projection[
                    "binding_authority_sha256"
                ],
                "scope_as_of": context["cutoff"].isoformat(),
            },
        )
        return self._pilot_projection(result)

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
            raise ValueError("Read-only Pilot limit must be 1 to 500")
        with Session(self.engine) as session:
            ids = list(
                session.scalars(
                    self._pilot_query(context)
                    .order_by(
                        ReadOnlyPilotRow.created_at.desc(),
                        ReadOnlyPilotRow.id,
                    )
                    .limit(limit)
                    .with_only_columns(ReadOnlyPilotRow.id)
                )
            )
        items = [
            self._pilot_projection(self.pilots.get(pilot_id))
            for pilot_id in ids
        ]
        return self._collection(context=context, items=items)

    def get(
        self,
        pilot_id: str,
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
        self._pilot_id(pilot_id, context=context)
        return self._pilot_projection(self.pilots.get(pilot_id))

    def evaluate(
        self,
        pilot_id: str,
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
        self._pilot_id(pilot_id, context=context)
        self._require_current_pilot_evidence(
            pilot_id,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=context["cutoff"],
        )
        payload = self.pilots.evaluate(
            pilot_id,
            as_of=context["cutoff"].isoformat(),
        )
        return {
            **payload,
            "scope": context["scope"],
            "external_write_allowed": False,
        }

    def require_pilot(
        self,
        pilot_id: str,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        pilot = self.get(
            pilot_id,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        self._require_current_pilot_evidence(
            pilot_id,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        return pilot

    def list_runs(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        pilot_id: str | None = None,
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
            return self._run_collection(context=context, items=[])
        if limit < 1 or limit > 500:
            raise ValueError("Read-only Pilot run limit must be 1 to 500")
        query = (
            select(ReadOnlyPilotRunRow.id)
            .join(
                ReadOnlyPilotRow,
                ReadOnlyPilotRow.id == ReadOnlyPilotRunRow.pilot_id,
            )
            .where(
                ReadOnlyPilotRow.tenant_ref
                == context["scope"]["tenant_ref"],
                ReadOnlyPilotRow.entity_ref
                == context["scope"]["entity_ref"],
                ReadOnlyPilotRow.store_ref
                == context["scope"]["store_ref"],
                ReadOnlyPilotRow.scope_as_of <= context["cutoff"],
                ReadOnlyPilotRow.created_at <= context["cutoff"],
                ReadOnlyPilotRunRow.started_at <= context["cutoff"],
            )
        )
        if pilot_id is not None:
            query = query.where(
                ReadOnlyPilotRunRow.pilot_id == pilot_id
            )
        with Session(self.engine) as session:
            ids = list(
                session.scalars(
                    query.order_by(
                        ReadOnlyPilotRunRow.started_at.desc(),
                        ReadOnlyPilotRunRow.id,
                    ).limit(limit)
                )
            )
        items = [
            self._run_projection(
                self.pilot_runs.get(run_id),
                context=context,
            )
            for run_id in ids
        ]
        return self._run_collection(context=context, items=items)

    def get_run(
        self,
        run_id: str,
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
        self._run_id(run_id, context=context)
        return self._run_projection(
            self.pilot_runs.get(run_id),
            context=context,
        )

    def require_run(
        self,
        run_id: str,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        run = self.get_run(
            run_id,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        self.require_pilot(
            run["pilot_id"],
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        return run

    def usage(
        self,
        pilot_id: str,
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
        self._pilot_id(pilot_id, context=context)
        return {
            **self.pilot_runs.usage(
                pilot_id,
                as_of=context["cutoff"].isoformat(),
            ),
            "scope": context["scope"],
            "external_write_allowed": False,
        }

    def reap_expired(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
        limit: int,
        actor_id: str,
    ) -> dict[str, Any]:
        context = self._context(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
            require_entity=True,
        )
        with Session(self.engine) as session:
            pilot_ids = set(
                session.scalars(
                    self._pilot_query(context).with_only_columns(
                        ReadOnlyPilotRow.id
                    )
                )
            )
        result = self.pilot_runs.reap_expired(
            as_of=context["cutoff"].isoformat(),
            limit=limit,
            actor_id=actor_id,
            pilot_ids=pilot_ids,
        )
        return {
            **result,
            "scope": context["scope"],
            "external_write_allowed": False,
        }

    def _pilot_id(
        self,
        pilot_id: str,
        *,
        context: dict[str, Any],
    ) -> str:
        with Session(self.engine) as session:
            found = session.scalar(
                self._pilot_query(context)
                .where(ReadOnlyPilotRow.id == pilot_id)
                .with_only_columns(ReadOnlyPilotRow.id)
            )
        if found is None:
            raise KeyError(
                "Read-only Pilot not found in authorized scope"
            )
        return found

    def _run_id(
        self,
        run_id: str,
        *,
        context: dict[str, Any],
    ) -> str:
        with Session(self.engine) as session:
            found = session.scalar(
                select(ReadOnlyPilotRunRow.id)
                .join(
                    ReadOnlyPilotRow,
                    ReadOnlyPilotRow.id
                    == ReadOnlyPilotRunRow.pilot_id,
                )
                .where(
                    ReadOnlyPilotRunRow.id == run_id,
                    ReadOnlyPilotRow.tenant_ref
                    == context["scope"]["tenant_ref"],
                    ReadOnlyPilotRow.entity_ref
                    == context["scope"]["entity_ref"],
                    ReadOnlyPilotRow.store_ref
                    == context["scope"]["store_ref"],
                    ReadOnlyPilotRow.scope_as_of
                    <= context["cutoff"],
                    ReadOnlyPilotRow.created_at <= context["cutoff"],
                    ReadOnlyPilotRunRow.started_at
                    <= context["cutoff"],
                )
            )
        if found is None:
            raise KeyError(
                "Read-only Pilot run not found in authorized scope"
            )
        return found

    @staticmethod
    def _pilot_query(context: dict[str, Any]):
        return select(ReadOnlyPilotRow).where(
            ReadOnlyPilotRow.tenant_ref
            == context["scope"]["tenant_ref"],
            ReadOnlyPilotRow.entity_ref
            == context["scope"]["entity_ref"],
            ReadOnlyPilotRow.store_ref
            == context["scope"]["store_ref"],
            ReadOnlyPilotRow.scope_as_of <= context["cutoff"],
            ReadOnlyPilotRow.created_at <= context["cutoff"],
        )

    def _require_current_pilot_evidence(
        self,
        pilot_id: str,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> None:
        pilot = self.pilots.get(pilot_id)
        projection = self._require_evidence(
            evidence_ids=pilot["evidence_ids"],
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        frozen = pilot["scope"][
            "scope_evidence_authority_sha256"
        ]
        if projection["binding_authority_sha256"] != frozen:
            raise ValueError(
                "Read-only Pilot Evidence authority changed; create a "
                "new reviewed Pilot"
            )

    def _require_evidence(
        self,
        *,
        evidence_ids: list[str],
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        normalized = sorted(
            {
                str(evidence_id).strip()
                for evidence_id in evidence_ids
                if str(evidence_id).strip()
            }
        )
        if not normalized or len(normalized) != len(evidence_ids):
            raise ValueError(
                "Read-only Pilot requires unique scoped Evidence"
            )
        projection = self.scoped_evidence.project_targets(
            evidence_ids=normalized,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        targets = {
            item["evidence_id"]: item
            for item in projection["records"]
            if item["evidence_id"] in normalized
        }
        if (
            projection["status"] != "ready"
            or projection["invalid_evidence_ids"]
            or set(targets) != set(normalized)
            or any(
                item["scope_binding"]["status"] != "ready"
                for item in targets.values()
            )
            or not projection["binding_authority_sha256"]
        ):
            raise ValueError(
                "Read-only Pilot Evidence is not current and "
                "independently bound to the exact tenant/entity/store"
            )
        return projection

    def _collection(
        self,
        *,
        context: dict[str, Any],
        items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload = {
            "contract_id": self.CONTRACT_ID,
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
            "counts": {"pilots": len(items)},
            "source_gaps": (
                []
                if items
                else [
                    context.get("reason")
                    or "scoped_read_only_pilot_not_available"
                ]
            ),
            "external_write_allowed": False,
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def _run_collection(
        self,
        *,
        context: dict[str, Any],
        items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload = self._collection(context=context, items=[])
        payload["items"] = items
        payload["counts"] = {"runs": len(items)}
        payload["status"] = (
            "ready"
            if items
            else context["status"]
            if context["status"] != "ready"
            else "no_data"
        )
        payload["source_gaps"] = (
            []
            if items
            else [
                context.get("reason")
                or "scoped_read_only_pilot_run_not_available"
            ]
        )
        payload["snapshot_sha256"] = self._hash(
            {
                key: value
                for key, value in payload.items()
                if key != "snapshot_sha256"
            }
        )
        return payload

    @staticmethod
    def _pilot_projection(value: dict[str, Any]) -> dict[str, Any]:
        return {
            **value,
            "external_write_allowed": False,
        }

    @staticmethod
    def _run_projection(
        value: dict[str, Any],
        *,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            **value,
            "scope": context["scope"],
            "external_write_allowed": False,
        }

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
                "Read-only Pilot requires one current entity scope grant"
            )
        status = (
            "ready"
            if ready
            else "blocked"
            if entity_scope.get("status") == "blocked"
            else "no_data"
        )
        reason = (
            None
            if ready
            else entity_scope.get(
                "reason",
                "entity_scope_authority_missing",
            )
        )
        return {
            "status": status,
            "reason": reason,
            "cutoff": cutoff,
            "scope": {
                "tenant_ref": principal.tenant_ref,
                "entity_ref": (
                    str(entity_scope["entity_ref"])
                    if ready
                    else None
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

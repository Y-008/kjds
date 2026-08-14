from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Integer,
    String,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .security import Principal
from .sql_repository import Base


class OperationsEscalationEventRow(Base):
    __tablename__ = "operations_escalation_events"
    __table_args__ = (
        UniqueConstraint("queue_key", "level", name="uq_operations_escalation_level"),
        CheckConstraint(
            "("
            "tenant_ref IS NULL AND entity_ref IS NULL AND store_ref IS NULL "
            "AND scope_authority_sha256 IS NULL"
            ") OR ("
            "tenant_ref IS NOT NULL AND length(tenant_ref) > 0 "
            "AND entity_ref IS NOT NULL AND length(entity_ref) > 0 "
            "AND store_ref IS NOT NULL AND length(store_ref) > 0 "
            "AND scope_authority_sha256 IS NOT NULL "
            "AND length(scope_authority_sha256) = 64"
            ")",
            name="ck_operations_escalation_scope_complete",
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    queue_key: Mapped[str] = mapped_column(String, nullable=False)
    item_type: Mapped[str] = mapped_column(String, nullable=False)
    item_id: Mapped[str] = mapped_column(String, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    tenant_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    entity_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    store_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    scope_authority_sha256: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    escalated_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OperationsQueueService:
    INCIDENT_SLA_MINUTES = {"critical": 15, "high": 30, "medium": 240, "low": 1440}

    def __init__(
        self,
        *,
        engine,
        incidents,
        limited_executor,
        post_execution,
        operating_tasks=None,
        governance_scope=None,
    ) -> None:
        self.engine = engine
        self.incidents = incidents
        self.limited_executor = limited_executor
        self.post_execution = post_execution
        self.operating_tasks = operating_tasks
        self.governance_scope = governance_scope

    def projection(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        now = self._datetime(as_of) if as_of else datetime.now(UTC)
        scope = self._scope(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
        )
        if scope is None:
            return {
                "contract_id": "kjds-scoped-operations-queue-v1",
                "status": "no_data",
                "scope": {
                    "tenant_ref": principal.tenant_ref,
                    "entity_ref": None,
                    "store_ref": store_ref,
                    "scope_authority_sha256": None,
                },
                "as_of": self._iso(now),
                "items": [],
                "source_gaps": ["entity_scope_authority_missing"],
                "excluded_sources": ["legacy_unscoped_incidents"],
                "external_write_allowed": False,
            }
        governance = (
            self.governance_scope.project(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                as_of=now,
            )
            if self.governance_scope is not None
            else {
                "status": "no_data",
                "commands": [],
                "windows": [],
                "source_gaps": ["governance_scope_authority_unavailable"],
            }
        )
        items = self._scoped_governance_items(
            commands=governance["commands"],
            windows=governance["windows"],
            now=now,
        )
        if self.operating_tasks is not None:
            items.extend(
                self.operating_tasks.queue_items(
                    now=now,
                    principal=principal,
                    entity_scope=entity_scope,
                    store_ref=store_ref,
                )
            )
        items = self._sort(items)
        source_gaps = sorted(set(governance.get("source_gaps", [])))
        return {
            "contract_id": "kjds-scoped-operations-queue-v1",
            "status": (
                "ready"
                if items and not source_gaps
                else "partial"
                if items
                else "no_data"
            ),
            "scope": scope,
            "as_of": self._iso(now),
            "items": items,
            "source_gaps": source_gaps,
            "excluded_sources": ["legacy_unscoped_incidents"],
            "external_write_allowed": False,
        }

    def queue(self, *, as_of: str | None = None) -> list[dict[str, Any]]:
        now = self._datetime(as_of) if as_of else datetime.now(UTC)
        items: list[dict[str, Any]] = []
        for incident in self.incidents.list():
            if incident["status"] == "closed":
                continue
            sla = self.INCIDENT_SLA_MINUTES[incident["severity"]]
            created = self._datetime(incident["created_at"])
            items.append(
                self._item(
                    queue_key=f"incident:{incident['id']}",
                    item_type="incident",
                    item_id=incident["id"],
                    title=incident["summary"],
                    status=incident["status"],
                    priority=incident["severity"],
                    owner_id=incident["owner_id"],
                    created_at=created,
                    due_at=created + timedelta(minutes=sla),
                    sla_minutes=sla,
                    now=now,
                    next_action=self._incident_action(incident),
                )
            )
        for command in self.limited_executor.list():
            if command["status"] not in {
                "queued",
                "claimed",
                "write_started",
                "uncertain",
                "precondition_failed",
            }:
                continue
            created = self._datetime(command["created_at"])
            if command["status"] in {"claimed", "write_started"} and command["lease_expires_at"]:
                due_at = self._datetime(command["lease_expires_at"])
                sla = max(1, int((due_at - created).total_seconds() / 60))
            else:
                sla = 5 if command["status"] == "uncertain" else 15
                due_at = created + timedelta(minutes=sla)
            items.append(
                self._item(
                    queue_key=f"execution_command:{command['id']}",
                    item_type="execution_command",
                    item_id=command["id"],
                    title=f"{command['command_kind']} · {command['operation']}",
                    status=command["status"],
                    priority=(
                        "critical"
                        if command["status"] in {"write_started", "uncertain"}
                        else "high"
                    ),
                    owner_id=command["claimed_by"],
                    created_at=created,
                    due_at=due_at,
                    sla_minutes=sla,
                    now=now,
                    next_action=(
                        "人工核对远端状态并登记事故"
                        if command["status"] in {"uncertain", "precondition_failed"}
                        else "由隔离执行器领取并回传不可变回执"
                    ),
                )
            )
        for window in self.post_execution.list_windows():
            evaluation = window["evaluation"]
            if evaluation["status"] not in {"monitoring", "insufficient_observations"}:
                continue
            created = self._datetime(window["created_at"])
            due_at = self._datetime(window["ends_at"])
            sla = max(1, int((due_at - created).total_seconds() / 60))
            items.append(
                self._item(
                    queue_key=f"observation_window:{window['id']}",
                    item_type="observation_window",
                    item_id=window["id"],
                    title=f"观察 {window['primary_metric']}",
                    status=evaluation["status"],
                    priority="high" if evaluation["status"] == "insufficient_observations" else "medium",
                    owner_id=window["created_by"],
                    created_at=created,
                    due_at=due_at,
                    sla_minutes=sla,
                    now=now,
                    next_action=(
                        "补齐预注册结果证据或正式记录样本不足"
                        if evaluation["status"] == "insufficient_observations"
                        else "按观察合同持续上报主指标与护栏指标"
                    ),
                )
            )
        if self.operating_tasks is not None:
            items.extend(self.operating_tasks.queue_items(now=now))
        return self._sort(items)

    def scan(
        self,
        *,
        as_of: str | None,
        actor_id: str,
        principal: Principal | None = None,
        entity_scope: dict[str, Any] | None = None,
        store_ref: str | None = None,
    ) -> dict[str, Any]:
        actor_id = actor_id.strip()
        if not actor_id:
            raise ValueError("Operations escalation actor is required")
        scoped = any(
            value is not None
            for value in (principal, entity_scope, store_ref)
        )
        if scoped:
            if principal is None or entity_scope is None or store_ref is None:
                raise ValueError(
                    "Scoped escalation scan requires principal, "
                    "entity_scope, and store_ref"
                )
            projection = self.projection(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                as_of=as_of,
            )
            if projection["status"] == "no_data":
                return {
                    "scanned_count": 0,
                    "overdue_count": 0,
                    "new_escalation_ids": [],
                    "status": "no_data",
                    "persisted": False,
                    "scope": projection["scope"],
                    "automatic_business_action": False,
                    "external_write_allowed": False,
                }
            items = projection["items"]
            frozen_scope = projection["scope"]
        else:
            items = self.queue(as_of=as_of)
            frozen_scope = None
        created: list[str] = []
        with Session(self.engine) as session, session.begin():
            for item in items:
                level = item["escalation_level"]
                if level == 0:
                    continue
                for current_level in range(1, level + 1):
                    existing = session.scalar(
                        select(OperationsEscalationEventRow).where(
                            OperationsEscalationEventRow.queue_key == item["queue_key"],
                            OperationsEscalationEventRow.level == current_level,
                        )
                    )
                    if existing is not None:
                        continue
                    row = OperationsEscalationEventRow(
                        id=new_id("ose"),
                        queue_key=item["queue_key"],
                        item_type=item["item_type"],
                        item_id=item["item_id"],
                        level=current_level,
                        tenant_ref=(
                            frozen_scope["tenant_ref"]
                            if frozen_scope is not None
                            else None
                        ),
                        entity_ref=(
                            frozen_scope["entity_ref"]
                            if frozen_scope is not None
                            else None
                        ),
                        store_ref=(
                            frozen_scope["store_ref"]
                            if frozen_scope is not None
                            else None
                        ),
                        scope_authority_sha256=(
                            frozen_scope["scope_authority_sha256"]
                            if frozen_scope is not None
                            else None
                        ),
                        due_at=self._datetime(item["due_at"]),
                        escalated_by=actor_id,
                        created_at=datetime.now(UTC),
                    )
                    session.add(row)
                    session.flush()
                    created.append(row.id)
        return {
            "scanned_count": len(items),
            "overdue_count": sum(item["overdue"] for item in items),
            "new_escalation_ids": created,
            "status": "ready",
            "persisted": True,
            "scope": frozen_scope,
            "automatic_business_action": False,
            "external_write_allowed": False,
        }

    def escalations(
        self,
        *,
        principal: Principal | None = None,
        entity_scope: dict[str, Any] | None = None,
        store_ref: str | None = None,
    ) -> list[dict[str, Any]]:
        scoped = any(
            value is not None
            for value in (principal, entity_scope, store_ref)
        )
        scope = None
        if scoped:
            if principal is None or entity_scope is None or store_ref is None:
                raise ValueError(
                    "Scoped escalation list requires principal, "
                    "entity_scope, and store_ref"
                )
            scope = self._scope(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
            )
            if scope is None:
                return []
        with Session(self.engine) as session:
            query = select(OperationsEscalationEventRow)
            if scope is not None:
                query = query.where(
                    OperationsEscalationEventRow.tenant_ref
                    == scope["tenant_ref"],
                    OperationsEscalationEventRow.entity_ref
                    == scope["entity_ref"],
                    OperationsEscalationEventRow.store_ref
                    == scope["store_ref"],
                    OperationsEscalationEventRow.scope_authority_sha256
                    == scope["scope_authority_sha256"],
                )
            rows = list(
                session.scalars(
                    query.order_by(
                        OperationsEscalationEventRow.created_at,
                        OperationsEscalationEventRow.level,
                    )
                )
            )
            return [
                {
                    "id": row.id,
                    "queue_key": row.queue_key,
                    "item_type": row.item_type,
                    "item_id": row.item_id,
                    "level": row.level,
                    "scope": (
                        {
                            "tenant_ref": row.tenant_ref,
                            "entity_ref": row.entity_ref,
                            "store_ref": row.store_ref,
                            "scope_authority_sha256": (
                                row.scope_authority_sha256
                            ),
                        }
                        if row.tenant_ref is not None
                        else None
                    ),
                    "due_at": self._iso(row.due_at),
                    "escalated_by": row.escalated_by,
                    "created_at": self._iso(row.created_at),
                    "immutable": True,
                }
                for row in rows
            ]

    def _scoped_governance_items(
        self,
        *,
        commands: list[dict[str, Any]],
        windows: list[dict[str, Any]],
        now: datetime,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for command in commands:
            if command["status"] not in {
                "queued",
                "claimed",
                "write_started",
                "uncertain",
                "precondition_failed",
            }:
                continue
            created = self._datetime(command["created_at"])
            if (
                command["status"] in {"claimed", "write_started"}
                and command["lease_expires_at"]
            ):
                due_at = self._datetime(command["lease_expires_at"])
                sla = max(
                    1,
                    int((due_at - created).total_seconds() / 60),
                )
            else:
                sla = 5 if command["status"] == "uncertain" else 15
                due_at = created + timedelta(minutes=sla)
            items.append(
                self._item(
                    queue_key=f"execution_command:{command['id']}",
                    item_type="execution_command",
                    item_id=command["id"],
                    title=(
                        f"{command['command_kind']} · "
                        f"{command['operation']}"
                    ),
                    status=command["status"],
                    priority=(
                        "critical"
                        if command["status"]
                        in {"write_started", "uncertain"}
                        else "high"
                    ),
                    owner_id=command["claimed_by"],
                    created_at=created,
                    due_at=due_at,
                    sla_minutes=sla,
                    now=now,
                    next_action=(
                        "人工核对远端状态并登记事故"
                        if command["status"]
                        in {"uncertain", "precondition_failed"}
                        else "由隔离执行器领取并回传不可变回执"
                    ),
                )
            )
        for window in windows:
            evaluation = window["evaluation"]
            if (
                not isinstance(evaluation, dict)
                or evaluation.get("status")
                not in {"monitoring", "insufficient_observations"}
            ):
                continue
            created = self._datetime(window["created_at"])
            due_at = self._datetime(window["ends_at"])
            sla = max(
                1,
                int((due_at - created).total_seconds() / 60),
            )
            items.append(
                self._item(
                    queue_key=f"observation_window:{window['id']}",
                    item_type="observation_window",
                    item_id=window["id"],
                    title=f"观察 {window['primary_metric']}",
                    status=evaluation["status"],
                    priority=(
                        "high"
                        if evaluation["status"]
                        == "insufficient_observations"
                        else "medium"
                    ),
                    owner_id=window["created_by"],
                    created_at=created,
                    due_at=due_at,
                    sla_minutes=sla,
                    now=now,
                    next_action=(
                        "补齐预注册结果证据或正式记录样本不足"
                        if evaluation["status"]
                        == "insufficient_observations"
                        else "按观察合同持续上报主指标与护栏指标"
                    ),
                )
            )
        return items

    @staticmethod
    def _scope(
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
    ) -> dict[str, str] | None:
        if not principal.can_access_store(store_ref):
            raise PermissionError(
                "Authenticated identity is not authorized for store_ref"
            )
        entity_ref = str(entity_scope.get("entity_ref") or "").strip()
        authority = entity_scope.get("authority_sha256")
        if (
            entity_scope.get("status") != "ready"
            or not entity_ref
        ):
            return None
        if (
            not isinstance(authority, str)
            or len(authority) != 64
            or any(
                character not in "0123456789abcdef"
                for character in authority
            )
        ):
            raise ValueError(
                "Ready entity scope requires a SHA-256 authority hash"
            )
        return {
            "tenant_ref": principal.tenant_ref,
            "entity_ref": entity_ref,
            "store_ref": store_ref,
            "scope_authority_sha256": authority,
        }

    @staticmethod
    def _sort(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        return sorted(
            items,
            key=lambda item: (
                not item["overdue"],
                rank[item["priority"]],
                item["due_at"],
            ),
        )

    @classmethod
    def _item(
        cls,
        *,
        queue_key: str,
        item_type: str,
        item_id: str,
        title: str,
        status: str,
        priority: str,
        owner_id: str | None,
        created_at: datetime,
        due_at: datetime,
        sla_minutes: int,
        now: datetime,
        next_action: str,
    ) -> dict[str, Any]:
        overdue_minutes = max(0, int((now - due_at).total_seconds() / 60))
        level = 0 if overdue_minutes == 0 else 3 if overdue_minutes >= sla_minutes * 3 else 2 if overdue_minutes >= sla_minutes else 1
        return {
            "queue_key": queue_key,
            "item_type": item_type,
            "item_id": item_id,
            "title": title,
            "status": status,
            "priority": priority,
            "owner_id": owner_id,
            "created_at": cls._iso(created_at),
            "due_at": cls._iso(due_at),
            "sla_minutes": sla_minutes,
            "overdue": now > due_at,
            "overdue_minutes": overdue_minutes,
            "escalation_level": level,
            "next_action": next_action,
        }

    @staticmethod
    def _incident_action(incident: dict[str, Any]) -> str:
        return {
            "open": "领取事故并保持风险隔离",
            "contained": "领取事故并开始五项恢复检查",
            "recovering": "完成剩余恢复检查并提交独立复核",
            "pending_review": "由独立复核人判断是否允许解除熔断",
            "ready_for_release": "管理员明确解除熔断并关闭事故",
        }.get(incident["status"], "人工检查事故状态")

    @staticmethod
    def _datetime(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Operations timestamps must include timezone")
        return parsed.astimezone(UTC)

    @staticmethod
    def _iso(value: datetime) -> str:
        return (value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)).isoformat()

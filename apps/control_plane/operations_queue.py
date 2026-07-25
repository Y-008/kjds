from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .sql_repository import Base


class OperationsEscalationEventRow(Base):
    __tablename__ = "operations_escalation_events"
    __table_args__ = (
        UniqueConstraint("queue_key", "level", name="uq_operations_escalation_level"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    queue_key: Mapped[str] = mapped_column(String, nullable=False)
    item_type: Mapped[str] = mapped_column(String, nullable=False)
    item_id: Mapped[str] = mapped_column(String, nullable=False)
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    escalated_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OperationsQueueService:
    INCIDENT_SLA_MINUTES = {"critical": 15, "high": 30, "medium": 240, "low": 1440}

    def __init__(self, *, engine, incidents, limited_executor, post_execution) -> None:
        self.engine = engine
        self.incidents = incidents
        self.limited_executor = limited_executor
        self.post_execution = post_execution

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
        rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        return sorted(items, key=lambda item: (not item["overdue"], rank[item["priority"]], item["due_at"]))

    def scan(self, *, as_of: str | None, actor_id: str) -> dict[str, Any]:
        actor_id = actor_id.strip()
        if not actor_id:
            raise ValueError("Operations escalation actor is required")
        items = self.queue(as_of=as_of)
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
            "automatic_business_action": False,
        }

    def escalations(self) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            rows = list(
                session.scalars(
                    select(OperationsEscalationEventRow).order_by(
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
                    "due_at": self._iso(row.due_at),
                    "escalated_by": row.escalated_by,
                    "created_at": self._iso(row.created_at),
                    "immutable": True,
                }
                for row in rows
            ]

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

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .domain import new_id
from .sql_repository import Base, ContentAssetRow

METRIC_REGISTRY_VERSION = "operating-metrics/1.0.0"
TASK_STATUSES = {"open", "acknowledged", "in_progress", "resolved", "dismissed"}
TASK_TRANSITIONS = {
    "acknowledge": ("open", "acknowledged"),
    "start": ("acknowledged", "in_progress"),
    "resolve": ("in_progress", "resolved"),
    "dismiss": ("in_progress", "dismissed"),
}
METRIC_REGISTRY: tuple[dict[str, Any], ...] = (
    {
        "id": "profit_coverage_ratio",
        "label": "利润证据覆盖率",
        "unit": "ratio",
        "operator": "lt",
        "threshold": "0.95",
        "baseline": "required_legs/6",
        "minimum_sample": 1,
        "severity": "high",
        "cooldown_minutes": 1440,
        "owner": "finance",
        "evidence_required": True,
        "causal_claim": False,
    },
    {
        "id": "negative_cm3",
        "label": "负 CM3",
        "unit": "CNY",
        "operator": "lt",
        "threshold": "0",
        "baseline": "reconciled_or_accrual_contribution",
        "minimum_sample": 1,
        "severity": "critical",
        "cooldown_minutes": 720,
        "owner": "finance",
        "evidence_required": True,
        "causal_claim": False,
    },
    {
        "id": "return_rate_spike",
        "label": "退货侵蚀突增",
        "unit": "ratio",
        "operator": "gt",
        "threshold": "0.12",
        "baseline": "return_erosion/gross_revenue",
        "minimum_sample": 30,
        "severity": "high",
        "cooldown_minutes": 1440,
        "owner": "operations",
        "evidence_required": True,
        "causal_claim": False,
    },
    {
        "id": "storage_erosion_ratio",
        "label": "库龄与仓储侵蚀",
        "unit": "ratio",
        "operator": "gt",
        "threshold": "0.08",
        "baseline": "warehousing_erosion/gross_revenue",
        "minimum_sample": 1,
        "severity": "medium",
        "cooldown_minutes": 1440,
        "owner": "supply",
        "evidence_required": True,
        "causal_claim": False,
    },
    {
        "id": "advertising_ceiling_breach",
        "label": "广告上限突破",
        "unit": "ratio",
        "operator": "gt",
        "threshold": "0.15",
        "baseline": "advertising_erosion/gross_revenue",
        "minimum_sample": 1,
        "severity": "high",
        "cooldown_minutes": 720,
        "owner": "growth",
        "evidence_required": True,
        "causal_claim": False,
    },
    {
        "id": "settlement_variance_ratio",
        "label": "结算到账差异",
        "unit": "ratio",
        "operator": "gt",
        "threshold": "0.01",
        "baseline": "abs(settlement-cash)/abs(settlement)",
        "minimum_sample": 1,
        "severity": "critical",
        "cooldown_minutes": 240,
        "owner": "finance",
        "evidence_required": True,
        "causal_claim": False,
    },
    {
        "id": "content_qa_failure_ratio",
        "label": "内容 QA 失败率",
        "unit": "ratio",
        "operator": "gt",
        "threshold": "0",
        "baseline": "qa_failed/reviewed_assets",
        "minimum_sample": 1,
        "severity": "medium",
        "cooldown_minutes": 720,
        "owner": "content",
        "evidence_required": False,
        "causal_claim": False,
    },
    {
        "id": "media_execution_failure_ratio",
        "label": "媒体执行失败率",
        "unit": "ratio",
        "operator": "gt",
        "threshold": "0",
        "baseline": "failed/terminal_media_jobs",
        "minimum_sample": 1,
        "severity": "medium",
        "cooldown_minutes": 240,
        "owner": "content",
        "evidence_required": False,
        "causal_claim": False,
    },
)


class OperatingTaskRow(Base):
    __tablename__ = "operating_tasks"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    metric_id: Mapped[str] = mapped_column(String, nullable=False)
    scope_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False)
    owner: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    first_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cooldown_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OperatingTaskEventRow(Base):
    __tablename__ = "operating_task_events"
    __table_args__ = (
        UniqueConstraint(
            "task_id", "sequence", name="uq_operating_task_event_sequence"
        ),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("operating_tasks.id"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    from_status: Mapped[str] = mapped_column(String, nullable=False)
    to_status: Mapped[str] = mapped_column(String, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    actor_id: Mapped[str] = mapped_column(String, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AnomalyScanRunRow(Base):
    __tablename__ = "anomaly_scan_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    registry_version: Mapped[str] = mapped_column(String, nullable=False)
    store_ref: Mapped[str] = mapped_column(String, nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    results_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OperatingIntelligenceService:
    """Evaluate server-owned metrics and close anomalies into one task interface."""

    def __init__(self, *, engine, profit_ledger, evidence) -> None:
        self.engine = engine
        self.profit_ledger = profit_ledger
        self.evidence = evidence

    def metrics(self, *, store_ref: str = "ozon-primary") -> dict[str, Any]:
        observations = self._observations(store_ref=store_ref)
        items = [
            {
                **metric,
                "observation": observations[metric["id"]],
                "data_status": (
                    "ready"
                    if observations[metric["id"]]["sample_size"]
                    >= metric["minimum_sample"]
                    else "no_data"
                ),
            }
            for metric in METRIC_REGISTRY
        ]
        payload = {
            "contract_id": "kjds-operating-metric-registry-v1",
            "registry_version": METRIC_REGISTRY_VERSION,
            "store_ref": store_ref,
            "metrics": items,
            "control_envelope": {
                "descriptive_not_causal": True,
                "client_can_change_thresholds": False,
                "external_write_allowed": False,
            },
        }
        payload["snapshot_sha256"] = self._hash(payload)
        return payload

    def scan(
        self,
        *,
        store_ref: str,
        actor_id: str,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        actor = actor_id.strip()
        if not actor:
            raise ValueError("Anomaly scan actor is required")
        now = self._datetime(as_of) if as_of else datetime.now(UTC)
        catalog = self.metrics(store_ref=store_ref)
        results: list[dict[str, Any]] = []
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            for metric in catalog["metrics"]:
                observation = metric["observation"]
                if observation["sample_size"] < metric["minimum_sample"]:
                    results.append(
                        {
                            "metric_id": metric["id"],
                            "status": "insufficient_sample",
                            "sample_size": observation["sample_size"],
                            "minimum_sample": metric["minimum_sample"],
                            "task_id": None,
                        }
                    )
                    continue
                value = Decimal(observation["value"])
                threshold = Decimal(metric["threshold"])
                anomalous = (
                    value < threshold
                    if metric["operator"] == "lt"
                    else value > threshold
                )
                if not anomalous:
                    results.append(
                        {
                            "metric_id": metric["id"],
                            "status": "within_baseline",
                            "sample_size": observation["sample_size"],
                            "value": observation["value"],
                            "task_id": None,
                        }
                    )
                    continue
                scope = {"store_ref": store_ref, **observation.get("scope", {})}
                active = self._cooldown_task(
                    session,
                    metric_id=metric["id"],
                    scope=scope,
                    now=now,
                )
                if active is not None:
                    active.last_detected_at = now
                    active.updated_at = now
                    event = self._append_event_row(
                        session,
                        task=active,
                        event_type="observation",
                        from_status=active.status,
                        to_status=active.status,
                        reason="Anomaly repeated inside cooldown; no duplicate task created",
                        evidence_ids=observation["evidence_ids"],
                        payload={"observation": observation},
                        actor_id=actor,
                        occurred_at=now,
                    )
                    results.append(
                        {
                            "metric_id": metric["id"],
                            "status": "deduplicated",
                            "task_id": active.id,
                            "event_id": event.id,
                            "fingerprint": active.fingerprint,
                        }
                    )
                    continue
                fingerprint = self._fingerprint(metric, scope, now)
                task = OperatingTaskRow(
                    id=new_id("tsk"),
                    fingerprint=fingerprint,
                    metric_id=metric["id"],
                    scope_json=scope,
                    title=f"{metric['label']} · {observation['value']} {metric['unit']}",
                    severity=metric["severity"],
                    owner=metric["owner"],
                    status="open",
                    first_detected_at=now,
                    last_detected_at=now,
                    cooldown_until=now
                    + timedelta(minutes=metric["cooldown_minutes"]),
                    evidence_ids_json=observation["evidence_ids"],
                    snapshot_json={
                        "policy": {
                            key: metric[key]
                            for key in (
                                "id",
                                "operator",
                                "threshold",
                                "baseline",
                                "minimum_sample",
                                "cooldown_minutes",
                            )
                        },
                        "observation": observation,
                        "automatic_business_action": False,
                    },
                    created_by=actor,
                    created_at=now,
                    updated_at=now,
                )
                session.add(task)
                session.flush()
                event = self._append_event_row(
                    session,
                    task=task,
                    event_type="opened",
                    from_status="open",
                    to_status="open",
                    reason="Server-owned metric policy detected an anomaly",
                    evidence_ids=observation["evidence_ids"],
                    payload={"observation": observation},
                    actor_id=actor,
                    occurred_at=now,
                )
                results.append(
                    {
                        "metric_id": metric["id"],
                        "status": "task_created",
                        "task_id": task.id,
                        "event_id": event.id,
                        "fingerprint": fingerprint,
                    }
                )
            run_payload = {
                "registry_version": METRIC_REGISTRY_VERSION,
                "store_ref": store_ref,
                "as_of": self._iso(now),
                "results": results,
            }
            run = AnomalyScanRunRow(
                id=new_id("asn"),
                registry_version=METRIC_REGISTRY_VERSION,
                store_ref=store_ref,
                as_of=now,
                results_json=results,
                snapshot_sha256=self._hash(run_payload),
                created_by=actor,
                created_at=datetime.now(UTC),
            )
            session.add(run)
            session.flush()
            return {
                "id": run.id,
                **run_payload,
                "snapshot_sha256": run.snapshot_sha256,
                "automatic_business_action": False,
                "external_write_allowed": False,
            }

    def tasks(
        self, *, status: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        if status is not None and status not in TASK_STATUSES:
            raise ValueError("Unknown operating task status")
        if not 1 <= limit <= 1000:
            raise ValueError("Operating task limit must be between 1 and 1000")
        query = select(OperatingTaskRow)
        if status:
            query = query.where(OperatingTaskRow.status == status)
        query = query.order_by(
            OperatingTaskRow.updated_at.desc(), OperatingTaskRow.id
        ).limit(limit)
        with Session(self.engine) as session:
            return [self._task(row) for row in session.scalars(query)]

    def ensure_internal_task(
        self,
        *,
        task_kind: str,
        scope: dict[str, Any],
        title: str,
        severity: str,
        owner: str,
        evidence_ids: list[str],
        snapshot: dict[str, Any],
        actor_id: str,
        cooldown_minutes: int = 1440,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        """Project an internal blocker into the existing task/event ledger."""
        task_kind = task_kind.strip()
        title = title.strip()
        owner = owner.strip()
        actor = actor_id.strip()
        if not task_kind or not title or not owner or not actor:
            raise ValueError(
                "Internal task requires kind, title, owner, and actor"
            )
        if severity not in {"critical", "high", "medium", "low"}:
            raise ValueError("Unknown internal task severity")
        if (
            not isinstance(scope, dict)
            or not scope
            or not isinstance(snapshot, dict)
        ):
            raise ValueError("Internal task requires scope and snapshot objects")
        if not 1 <= cooldown_minutes <= 525_600:
            raise ValueError(
                "Internal task cooldown must be 1 to 525600 minutes"
            )
        normalized_evidence = self._evidence_ids(evidence_ids)
        if normalized_evidence:
            self.evidence.require_valid(normalized_evidence)
        now = self._datetime(as_of) if as_of else datetime.now(UTC)
        metric_id = f"internal:{task_kind}"
        with Session(
            self.engine, expire_on_commit=False
        ) as session, session.begin():
            active = self._cooldown_task(
                session,
                metric_id=metric_id,
                scope=scope,
                now=now,
            )
            if active is not None:
                active.last_detected_at = now
                active.updated_at = now
                active.evidence_ids_json = sorted(
                    set(active.evidence_ids_json)
                    | set(normalized_evidence)
                )
                active.snapshot_json = {
                    **active.snapshot_json,
                    **snapshot,
                    "automatic_business_action": False,
                    "external_write_allowed": False,
                }
                self._append_event_row(
                    session,
                    task=active,
                    event_type="observation",
                    from_status=active.status,
                    to_status=active.status,
                    reason=(
                        "Internal blocker repeated inside cooldown; "
                        "no duplicate task created"
                    ),
                    evidence_ids=normalized_evidence,
                    payload={"snapshot": snapshot},
                    actor_id=actor,
                    occurred_at=now,
                )
                session.flush()
                return self._task(active)
            bucket = int(now.timestamp()) // (cooldown_minutes * 60)
            fingerprint = hashlib.sha256(
                json.dumps(
                    {
                        "registry_version": "operating-internal-task/1.0.0",
                        "task_kind": task_kind,
                        "scope": scope,
                        "cooldown_bucket": bucket,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            task = OperatingTaskRow(
                id=new_id("tsk"),
                fingerprint=fingerprint,
                metric_id=metric_id,
                scope_json=scope,
                title=title,
                severity=severity,
                owner=owner,
                status="open",
                first_detected_at=now,
                last_detected_at=now,
                cooldown_until=now
                + timedelta(minutes=cooldown_minutes),
                evidence_ids_json=normalized_evidence,
                snapshot_json={
                    **snapshot,
                    "automatic_business_action": False,
                    "external_write_allowed": False,
                },
                created_by=actor,
                created_at=now,
                updated_at=now,
            )
            session.add(task)
            session.flush()
            self._append_event_row(
                session,
                task=task,
                event_type="opened",
                from_status="open",
                to_status="open",
                reason="Internal operating blocker projected by a deep module",
                evidence_ids=normalized_evidence,
                payload={"snapshot": snapshot},
                actor_id=actor,
                occurred_at=now,
            )
            session.flush()
            return self._task(task)

    def scans(self, *, limit: int = 50) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500:
            raise ValueError("Anomaly scan limit must be between 1 and 500")
        query = (
            select(AnomalyScanRunRow)
            .order_by(
                AnomalyScanRunRow.as_of.desc(),
                AnomalyScanRunRow.id,
            )
            .limit(limit)
        )
        with Session(self.engine) as session:
            return [
                {
                    "id": row.id,
                    "registry_version": row.registry_version,
                    "store_ref": row.store_ref,
                    "as_of": self._iso(row.as_of),
                    "results": row.results_json,
                    "snapshot_sha256": row.snapshot_sha256,
                    "created_by": row.created_by,
                    "created_at": self._iso(row.created_at),
                    "automatic_business_action": False,
                    "external_write_allowed": False,
                }
                for row in session.scalars(query)
            ]

    def append_task_event(
        self,
        task_id: str,
        *,
        event_type: str,
        reason: str,
        evidence_ids: list[str],
        actor_id: str,
    ) -> dict[str, Any]:
        event_type = event_type.strip().lower()
        reason = reason.strip()
        actor = actor_id.strip()
        if event_type not in TASK_TRANSITIONS:
            raise ValueError(
                "Task event_type must be acknowledge, start, resolve, or dismiss"
            )
        if not reason or not actor:
            raise ValueError("Task event requires reason and actor")
        normalized_evidence = self._evidence_ids(evidence_ids)
        if event_type in {"resolve", "dismiss"} and not normalized_evidence:
            raise ValueError("Resolved or dismissed task requires Evidence")
        if normalized_evidence:
            self.evidence.require_valid(normalized_evidence)
        expected, target = TASK_TRANSITIONS[event_type]
        now = datetime.now(UTC)
        with Session(self.engine, expire_on_commit=False) as session, session.begin():
            task = session.get(OperatingTaskRow, task_id)
            if task is None:
                raise KeyError(f"Unknown operating task: {task_id}")
            if task.status != expected:
                raise ValueError(
                    f"Task transition {event_type} requires status {expected}"
                )
            previous = task.status
            task.status = target
            task.updated_at = now
            if normalized_evidence:
                task.evidence_ids_json = sorted(
                    set(task.evidence_ids_json) | set(normalized_evidence)
                )
            event = self._append_event_row(
                session,
                task=task,
                event_type=event_type,
                from_status=previous,
                to_status=target,
                reason=reason,
                evidence_ids=normalized_evidence,
                payload={"automatic_business_action": False},
                actor_id=actor,
                occurred_at=now,
            )
            session.flush()
            return {"task": self._task(task), "event": self._event(event)}

    def task_events(self, task_id: str) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            if session.get(OperatingTaskRow, task_id) is None:
                raise KeyError(f"Unknown operating task: {task_id}")
            rows = session.scalars(
                select(OperatingTaskEventRow)
                .where(OperatingTaskEventRow.task_id == task_id)
                .order_by(
                    OperatingTaskEventRow.sequence, OperatingTaskEventRow.id
                )
            )
            return [self._event(row) for row in rows]

    def queue_items(self, *, now: datetime) -> list[dict[str, Any]]:
        rank = {"critical": 15, "high": 60, "medium": 240, "low": 1440}
        result: list[dict[str, Any]] = []
        with Session(self.engine) as session:
            rows = session.scalars(
                select(OperatingTaskRow)
                .where(
                    OperatingTaskRow.status.in_(
                        ("open", "acknowledged", "in_progress")
                    )
                )
                .order_by(OperatingTaskRow.created_at, OperatingTaskRow.id)
            )
            for row in rows:
                sla = rank[row.severity]
                created = self._aware(row.created_at)
                due = created + timedelta(minutes=sla)
                overdue = now > due
                overdue_minutes = max(
                    0, int((now - due).total_seconds() / 60)
                )
                level = (
                    0
                    if not overdue
                    else 3
                    if overdue_minutes >= sla * 3
                    else 2
                    if overdue_minutes >= sla
                    else 1
                )
                result.append(
                    {
                        "queue_key": f"operating_task:{row.id}",
                        "item_type": "operating_task",
                        "item_id": row.id,
                        "title": row.title,
                        "status": row.status,
                        "priority": row.severity,
                        "owner_id": row.owner,
                        "created_at": self._iso(created),
                        "due_at": self._iso(due),
                        "sla_minutes": sla,
                        "overdue": overdue,
                        "overdue_minutes": overdue_minutes,
                        "escalation_level": level,
                        "next_action": (
                            row.snapshot_json.get("next_action")
                            or "确认指标来源与 Evidence，并记录任务状态事件"
                        ),
                    }
                )
        return result

    def _observations(self, *, store_ref: str) -> dict[str, dict[str, Any]]:
        ledger = self.profit_ledger.snapshot(store_ref=store_ref, grain="order")
        rows = ledger["rows"]
        gross = sum((Decimal(item["gross_revenue"]) for item in rows), Decimal("0"))
        evidence_ids = sorted(
            {value for item in rows for value in item["evidence_ids"]}
        )
        contribution_values = [
            Decimal(item["actual_profit"] or item["accrual_contribution"])
            for item in rows
        ]
        settlement_pairs = [
            (
                Decimal(item["settlement_contribution"]),
                Decimal(item["cash_contribution"]),
            )
            for item in rows
            if item["settlement_contribution"] is not None
            and item["cash_contribution"] is not None
            and Decimal(item["settlement_contribution"]) != 0
        ]
        with Session(self.engine) as session:
            assets = list(session.scalars(select(ContentAssetRow)))
        reviewed = [
            item
            for item in assets
            if item.status in {"approved", "qa_failed", "published"}
        ]
        failed_assets = [item for item in reviewed if item.status == "qa_failed"]
        media_terminal = 0
        media_failed = 0
        try:
            from .media_workbench import MediaExecutionRow

            with Session(self.engine) as session:
                jobs = list(
                    session.scalars(
                        select(MediaExecutionRow).where(
                            MediaExecutionRow.status.in_(
                                ("generated", "approved", "failed")
                            )
                        )
                    )
                )
            media_terminal = len(jobs)
            media_failed = sum(item.status == "failed" for item in jobs)
        except (ImportError, RuntimeError):
            pass
        total_returns = sum(
            (Decimal(item["erosion"]["returns"]) for item in rows), Decimal("0")
        )
        total_storage = sum(
            (Decimal(item["erosion"]["warehousing"]) for item in rows), Decimal("0")
        )
        total_ads = sum(
            (Decimal(item["erosion"]["advertising"]) for item in rows), Decimal("0")
        )
        return {
            "profit_coverage_ratio": self._observation(
                ledger["coverage_ratio"], len(rows), evidence_ids
            ),
            "negative_cm3": self._observation(
                str(min(contribution_values)) if contribution_values else "0",
                len(contribution_values),
                evidence_ids,
            ),
            "return_rate_spike": self._observation(
                self._ratio(total_returns, gross), len(rows), evidence_ids
            ),
            "storage_erosion_ratio": self._observation(
                self._ratio(total_storage, gross), len(rows), evidence_ids
            ),
            "advertising_ceiling_breach": self._observation(
                self._ratio(total_ads, gross), len(rows), evidence_ids
            ),
            "settlement_variance_ratio": self._observation(
                (
                    str(
                        max(
                            abs(settlement - cash) / abs(settlement)
                            for settlement, cash in settlement_pairs
                        )
                    )
                    if settlement_pairs
                    else "0"
                ),
                len(settlement_pairs),
                evidence_ids,
            ),
            "content_qa_failure_ratio": self._observation(
                self._ratio(Decimal(len(failed_assets)), Decimal(len(reviewed))),
                len(reviewed),
                [],
            ),
            "media_execution_failure_ratio": self._observation(
                self._ratio(Decimal(media_failed), Decimal(media_terminal)),
                media_terminal,
                [],
            ),
        }

    @staticmethod
    def _observation(
        value: str, sample_size: int, evidence_ids: list[str]
    ) -> dict[str, Any]:
        return {
            "value": value,
            "sample_size": sample_size,
            "evidence_ids": evidence_ids,
            "scope": {},
        }

    @staticmethod
    def _ratio(numerator: Decimal, denominator: Decimal) -> str:
        if denominator == 0:
            return "0"
        return format((numerator / denominator).normalize(), "f")

    @staticmethod
    def _cooldown_task(
        session: Session,
        *,
        metric_id: str,
        scope: dict[str, Any],
        now: datetime,
    ) -> OperatingTaskRow | None:
        rows = session.scalars(
            select(OperatingTaskRow)
            .where(OperatingTaskRow.metric_id == metric_id)
            .order_by(OperatingTaskRow.last_detected_at.desc())
        )
        return next(
            (
                row
                for row in rows
                if row.scope_json == scope
                and (
                    row.status in {"open", "acknowledged", "in_progress"}
                    or OperatingIntelligenceService._aware(row.cooldown_until) > now
                )
            ),
            None,
        )

    @staticmethod
    def _fingerprint(
        metric: dict[str, Any], scope: dict[str, Any], now: datetime
    ) -> str:
        cooldown_seconds = metric["cooldown_minutes"] * 60
        bucket = int(now.timestamp()) // cooldown_seconds
        return hashlib.sha256(
            json.dumps(
                {
                    "registry_version": METRIC_REGISTRY_VERSION,
                    "metric_id": metric["id"],
                    "scope": scope,
                    "cooldown_bucket": bucket,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    @staticmethod
    def _append_event_row(
        session: Session,
        *,
        task: OperatingTaskRow,
        event_type: str,
        from_status: str,
        to_status: str,
        reason: str,
        evidence_ids: list[str],
        payload: dict[str, Any],
        actor_id: str,
        occurred_at: datetime,
    ) -> OperatingTaskEventRow:
        last_sequence = session.scalars(
            select(OperatingTaskEventRow.sequence)
            .where(OperatingTaskEventRow.task_id == task.id)
            .order_by(OperatingTaskEventRow.sequence.desc())
            .limit(1)
        ).first()
        event = OperatingTaskEventRow(
            id=new_id("tse"),
            task_id=task.id,
            sequence=(last_sequence or 0) + 1,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            reason=reason,
            evidence_ids_json=evidence_ids,
            payload_json=payload,
            actor_id=actor_id,
            occurred_at=occurred_at,
        )
        session.add(event)
        return event

    @staticmethod
    def _evidence_ids(values: list[str]) -> list[str]:
        if not isinstance(values, list):
            raise ValueError("Task evidence_ids must be a list")
        normalized = [item.strip() for item in values]
        if any(not item for item in normalized) or len(normalized) != len(set(normalized)):
            raise ValueError("Task evidence_ids must be non-empty and unique")
        return normalized

    @staticmethod
    def _task(row: OperatingTaskRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "fingerprint": row.fingerprint,
            "metric_id": row.metric_id,
            "scope": row.scope_json,
            "title": row.title,
            "severity": row.severity,
            "owner": row.owner,
            "status": row.status,
            "first_detected_at": OperatingIntelligenceService._iso(
                row.first_detected_at
            ),
            "last_detected_at": OperatingIntelligenceService._iso(
                row.last_detected_at
            ),
            "cooldown_until": OperatingIntelligenceService._iso(
                row.cooldown_until
            ),
            "evidence_ids": row.evidence_ids_json,
            "snapshot": row.snapshot_json,
            "created_by": row.created_by,
            "created_at": OperatingIntelligenceService._iso(row.created_at),
            "updated_at": OperatingIntelligenceService._iso(row.updated_at),
            "automatic_business_action": False,
        }

    @staticmethod
    def _event(row: OperatingTaskEventRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "task_id": row.task_id,
            "sequence": row.sequence,
            "event_type": row.event_type,
            "from_status": row.from_status,
            "to_status": row.to_status,
            "reason": row.reason,
            "evidence_ids": row.evidence_ids_json,
            "payload": row.payload_json,
            "actor_id": row.actor_id,
            "occurred_at": OperatingIntelligenceService._iso(row.occurred_at),
            "immutable": True,
        }

    @staticmethod
    def _datetime(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Operating intelligence timestamps require timezone")
        return parsed.astimezone(UTC)

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    @staticmethod
    def _iso(value: datetime) -> str:
        return OperatingIntelligenceService._aware(value).isoformat()

    @staticmethod
    def _hash(value: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

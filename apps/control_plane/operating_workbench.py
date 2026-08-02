from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any

from .security import Principal


class OperatingWorkbenchService:
    """Project existing control-plane facts into one advisory Agent briefing."""

    CONTRACT_ID = "kjds-operating-workbench-briefing-v1"
    SCOPED_AUTHORITY_CONTRACT_ID = "kjds-scoped-operating-workbench-v1"
    AGENTS = (
        ("digital_ceo", "Digital CEO"),
        ("evidence_compliance", "Evidence & Compliance Agent"),
        ("product_sourcing", "Product / Sourcing Agent"),
        ("finance_cash", "Finance & Cash Agent"),
        ("market_content", "Market / Content Agent"),
        ("experiment_scientist", "Experiment Scientist Agent"),
        ("risk_red_team", "Risk / Red-team Agent"),
        ("execution", "Execution Agent"),
        ("memory_curator", "Memory Curator"),
    )
    AGENT_LABELS = dict(AGENTS)
    PRIORITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}

    def __init__(self, *, readiness, operations_queue, automation) -> None:
        self.readiness = readiness
        self.operations_queue = operations_queue
        self.automation = automation

    def snapshot(
        self,
        *,
        limit: int = 20,
        principal: Principal | None = None,
        entity_scope: dict[str, Any] | None = None,
        store_ref: str | None = None,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        if limit < 1 or limit > 100:
            raise ValueError("Operating workbench limit must be between 1 and 100")
        context = (principal, entity_scope, store_ref)
        if any(value is not None for value in context):
            if any(value is None for value in context):
                raise ValueError(
                    "Scoped operating workbench requires principal, "
                    "entity_scope, and store_ref"
                )
            return self._scoped_snapshot(
                limit=limit,
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                as_of=as_of,
            )

        readiness = self.readiness.report()
        gate_items = [
            self._gate_item(item)
            for item in readiness["exception_workspace"]["items"]
        ]
        runtime_items = [
            self._runtime_item(item)
            for item in self.operations_queue.queue()
        ]
        recommendation_items = [
            self._recommendation_item(item.to_dict())
            for item in self.automation.list_recommendations()
        ]
        all_items = gate_items + runtime_items + recommendation_items
        all_items.sort(key=self._sort_key)
        visible_items = all_items[:limit]

        payload = {
            "contract_id": self.CONTRACT_ID,
            "mode": "shadow_advisory",
            "status": readiness["status"],
            "summary": {
                "gate_blockers": len(gate_items),
                "runtime_items": len(runtime_items),
                "recommendations": len(recommendation_items),
                "visible_items": len(visible_items),
                "candidate_count": readiness["candidate_portfolio"]["candidate_count"],
                "selection_ready_count": readiness["candidate_portfolio"][
                    "selection_ready_count"
                ],
            },
            "agents": self._agent_statuses(all_items),
            "work_items": visible_items,
            "candidate_portfolio": readiness["candidate_portfolio"],
            "guardrails": {
                "advisory_only": True,
                "automatic_execution": False,
                "automatic_product_selection": False,
                "automatic_procurement": False,
                "automatic_pricing": False,
                "automatic_listing": False,
                "platform_write_allowed": False,
                "third_party_fact_promotion_allowed": False,
            },
        }
        payload["snapshot_sha256"] = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode()
        ).hexdigest()
        return payload

    def _scoped_snapshot(
        self,
        *,
        limit: int,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: str | None,
    ) -> dict[str, Any]:
        queue = self.operations_queue.projection(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
        )
        runtime_items = [
            self._runtime_item(item)
            for item in queue["items"]
        ]
        runtime_items.sort(key=self._sort_key)
        visible_items = runtime_items[:limit]
        payload = {
            "contract_id": self.CONTRACT_ID,
            "mode": "scoped_shadow_advisory",
            "status": queue["status"],
            "scope": queue["scope"],
            "as_of": queue["as_of"],
            "summary": {
                "gate_blockers": 0,
                "runtime_items": len(runtime_items),
                "recommendations": 0,
                "visible_items": len(visible_items),
                "candidate_count": 0,
                "selection_ready_count": 0,
            },
            "agents": self._agent_statuses(runtime_items),
            "work_items": visible_items,
            "candidate_portfolio": {
                "status": "no_data",
                "candidate_count": 0,
                "selection_ready_count": 0,
                "rows": [],
                "source_gap": "scoped_readiness_authority_missing",
                "advisory_only": True,
            },
            "source_gaps": sorted(
                {
                    *queue.get("source_gaps", []),
                    "scoped_readiness_authority_missing",
                    "scoped_automation_recommendation_authority_missing",
                }
            ),
            "excluded_sources": sorted(
                {
                    *queue.get("excluded_sources", []),
                    "legacy_global_gate_readiness",
                    "legacy_global_automation_recommendations",
                }
            ),
            "guardrails": {
                "advisory_only": True,
                "automatic_execution": False,
                "automatic_product_selection": False,
                "automatic_procurement": False,
                "automatic_pricing": False,
                "automatic_listing": False,
                "platform_write_allowed": False,
                "third_party_fact_promotion_allowed": False,
            },
        }
        payload["snapshot_sha256"] = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode()
        ).hexdigest()
        return payload

    def _agent_statuses(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_agent: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in items:
            by_agent[item["agent_id"]].append(item)
        return [
            {
                "agent_id": agent_id,
                "name": name,
                "status": "needs_attention" if by_agent[agent_id] else "waiting_for_upstream",
                "work_item_count": len(by_agent[agent_id]),
                "current_focus": (
                    by_agent[agent_id][0]["title"]
                    if by_agent[agent_id]
                    else "等待有证据的上游输入"
                ),
                "automatic_execution": False,
            }
            for agent_id, name in self.AGENTS
        ]

    def _gate_item(self, item: dict[str, Any]) -> dict[str, Any]:
        agent_id = self._agent_for_owner(item["owner_role"])
        return {
            "id": item["queue_key"],
            "item_type": "gate_blocker",
            "source_type": item["source_type"],
            "source_id": item["source_id"],
            "agent_id": agent_id,
            "agent_name": self.AGENT_LABELS[agent_id],
            "title": item["title"],
            "status": item["status"],
            "priority": "high" if item["attention"] == "current_gate" else "low",
            "risk": "blocked",
            "next_action": item["next_action"],
            "human_required": True,
            "evidence_ids": [],
            "gate": item["gate"],
            "progress": {"current": item["current"], "target": item["target"]},
            "due_at": None,
            "overdue": None,
            "escalation_level": None,
            "automatic_execution": False,
            "platform_write_allowed": False,
        }

    def _runtime_item(self, item: dict[str, Any]) -> dict[str, Any]:
        agent_id = {
            "incident": "risk_red_team",
            "execution_command": "execution",
            "observation_window": "experiment_scientist",
        }.get(item["item_type"], "digital_ceo")
        return {
            "id": item["queue_key"],
            "item_type": "runtime_operation",
            "source_type": item["item_type"],
            "source_id": item["item_id"],
            "agent_id": agent_id,
            "agent_name": self.AGENT_LABELS[agent_id],
            "title": item["title"],
            "status": item["status"],
            "priority": item["priority"],
            "risk": item["priority"],
            "next_action": item["next_action"],
            "human_required": True,
            "evidence_ids": [],
            "gate": None,
            "progress": None,
            "due_at": item["due_at"],
            "overdue": item["overdue"],
            "escalation_level": item["escalation_level"],
            "automatic_execution": False,
            "platform_write_allowed": False,
        }

    def _recommendation_item(self, item: dict[str, Any]) -> dict[str, Any]:
        agent_id = self._agent_for_recommendation(item["agent"])
        return {
            "id": f"recommendation:{item['id']}",
            "item_type": "recommendation",
            "source_type": "decision_recommendation",
            "source_id": item["id"],
            "agent_id": agent_id,
            "agent_name": self.AGENT_LABELS[agent_id],
            "title": item["action"],
            "status": item["status"],
            "priority": {
                "high": "high",
                "medium": "medium",
                "low": "low",
            }.get(item["risk"], "medium"),
            "risk": item["risk"],
            "next_action": "由人工核对依据、预期收益和风险后决定是否建立正式决策合同",
            "human_required": True,
            "evidence_ids": list(item["evidence"]),
            "gate": None,
            "progress": None,
            "due_at": None,
            "overdue": None,
            "escalation_level": None,
            "expected_cm3_delta": (
                str(item["expected_cm3_delta"])
                if item["expected_cm3_delta"] is not None
                else None
            ),
            "automatic_execution": False,
            "platform_write_allowed": False,
        }

    def _sort_key(self, item: dict[str, Any]) -> tuple[int, int, str]:
        type_rank = {
            "runtime_operation": 0 if item["overdue"] else 2,
            "gate_blocker": 1,
            "recommendation": 3,
        }
        return (
            self.PRIORITY_RANK.get(item["priority"], 4),
            type_rank[item["item_type"]],
            item["id"],
        )

    @staticmethod
    def _agent_for_owner(owner_role: str) -> str:
        if "财务" in owner_role:
            return "finance_cash"
        if "合规" in owner_role:
            return "evidence_compliance"
        if "供应链" in owner_role or "商品" in owner_role:
            return "product_sourcing"
        if "账户" in owner_role:
            return "evidence_compliance"
        if "经营" in owner_role:
            return "digital_ceo"
        return "digital_ceo"

    @staticmethod
    def _agent_for_recommendation(agent: str) -> str:
        normalized = agent.casefold()
        if "finance" in normalized or "profit" in normalized or "财务" in normalized:
            return "finance_cash"
        if "risk" in normalized or "audit" in normalized or "风险" in normalized:
            return "risk_red_team"
        if "content" in normalized or "market" in normalized or "内容" in normalized:
            return "market_content"
        if "product" in normalized or "sourcing" in normalized or "商品" in normalized:
            return "product_sourcing"
        if "experiment" in normalized or "实验" in normalized:
            return "experiment_scientist"
        if "execution" in normalized or "执行" in normalized:
            return "execution"
        if "evidence" in normalized or "compliance" in normalized or "合规" in normalized:
            return "evidence_compliance"
        if "memory" in normalized or "记忆" in normalized:
            return "memory_curator"
        return "digital_ceo"

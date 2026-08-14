from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .security import Principal


class EvidenceOpsCopilot:
    """Compile one business objective into an evidence-backed, read-only task contract."""

    CONTRACT_ID = "kjds-evidenceops-copilot-plan-v1"
    INTENTS = (
        {
            "id": "profit_cash",
            "label": "利润与现金",
            "keywords": (
                "利润",
                "毛利",
                "cm3",
                "现金",
                "结算",
                "回款",
                "profit",
                "margin",
                "cash",
                "settlement",
            ),
            "stage_ids": ("sku-003", "ozn-002", "fin-001", "growth"),
            "workspaces": ("finance", "sourcing", "growth"),
        },
        {
            "id": "growth",
            "label": "增长与实验",
            "keywords": (
                "增长",
                "广告",
                "投放",
                "转化",
                "价格",
                "销量",
                "growth",
                "ads",
                "conversion",
                "price",
                "sales",
            ),
            "stage_ids": ("growth", "content", "execution"),
            "workspaces": ("growth", "products", "governance"),
        },
        {
            "id": "sourcing",
            "label": "供应链与采购准备",
            "keywords": (
                "供应商",
                "报价",
                "询价",
                "采购",
                "成本",
                "物流",
                "supplier",
                "quote",
                "sourcing",
                "procurement",
                "logistics",
            ),
            "stage_ids": ("sku-003", "content", "ozn-002"),
            "workspaces": ("sourcing", "products", "finance"),
        },
        {
            "id": "content_listing",
            "label": "内容与 Listing",
            "keywords": (
                "listing",
                "图片",
                "视频",
                "内容",
                "俄语",
                "上架",
                "素材",
                "content",
                "image",
                "video",
                "launch",
            ),
            "stage_ids": ("content", "growth", "execution"),
            "workspaces": ("products", "growth", "governance"),
        },
        {
            "id": "product_research",
            "label": "需求与选品",
            "keywords": (
                "选品",
                "新品",
                "需求",
                "市场",
                "竞品",
                "评论",
                "product",
                "research",
                "market",
                "competitor",
                "review",
            ),
            "stage_ids": ("sku-000", "sku-001", "sku-002"),
            "workspaces": ("research", "products"),
        },
    )
    DEFAULT_INTENT = {
        "id": "operating_readiness",
        "label": "经营就绪度",
        "keywords": (),
        "stage_ids": (),
        "workspaces": (),
    }
    WORKSPACE_AGENTS = {
        "research": ("product_sourcing", "Product / Sourcing Agent"),
        "products": ("market_content", "Market / Content Agent"),
        "sourcing": ("product_sourcing", "Product / Sourcing Agent"),
        "growth": ("experiment_scientist", "Experiment Scientist Agent"),
        "governance": ("risk_red_team", "Risk / Red-team Agent"),
        "finance": ("finance_cash", "Finance & Cash Agent"),
        "system": ("evidence_compliance", "Evidence & Compliance Agent"),
    }
    FORBIDDEN_ACTIONS = (
        "自动选择商品",
        "自动联系供应商",
        "自动采购或付款",
        "自动改价",
        "自动发布 Listing",
        "自动投放广告",
        "直接写入 Ozon 或第三方平台",
        "把用户目标或第三方营销信息晋升为经营事实",
    )

    def __init__(self, *, operating_analytics, operating_workbench) -> None:
        self.operating_analytics = operating_analytics
        self.operating_workbench = operating_workbench

    def plan(
        self,
        *,
        objective: str,
        store_ref: str = "ozon-primary",
        principal: Principal | None = None,
        entity_scope: dict[str, Any] | None = None,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        normalized_objective = self._normalize_text(objective)
        normalized_store_ref = store_ref.strip()
        if len(normalized_objective) < 3 or len(normalized_objective) > 1000:
            raise ValueError("EvidenceOps objective must be 3 to 1000 characters")
        if not normalized_store_ref or len(normalized_store_ref) > 160:
            raise ValueError("EvidenceOps store_ref must be 1 to 160 characters")

        context = (principal, entity_scope)
        if any(value is not None for value in context) or as_of is not None:
            if principal is None or entity_scope is None:
                raise ValueError(
                    "Scoped EvidenceOps requires principal and entity_scope"
                )
            analytics = self.operating_analytics.snapshot(
                store_ref=normalized_store_ref,
                principal=principal,
                entity_scope=entity_scope,
                as_of=as_of,
            )
            workbench = self.operating_workbench.snapshot(
                limit=100,
                principal=principal,
                entity_scope=entity_scope,
                store_ref=normalized_store_ref,
                as_of=as_of,
            )
        else:
            analytics = self.operating_analytics.snapshot(
                store_ref=normalized_store_ref
            )
            workbench = self.operating_workbench.snapshot(limit=100)
        intent = self._interpret_intent(normalized_objective)
        missions = self._missions(
            analytics=analytics,
            workbench=workbench,
            intent=intent,
        )
        verified_facts = self._verified_facts(analytics)
        unknowns = self._unknowns(analytics)
        agent_ids = {item["agent"]["id"] for item in missions}

        payload = {
            "contract_id": self.CONTRACT_ID,
            "product": {
                "id": "evidenceops-copilot",
                "name": "KJDS EvidenceOps Copilot",
                "version": "0.54.0",
                "positioning": "目标到证据任务合同，而不是无边界聊天或自动驾驶",
            },
            "objective": {
                "text": normalized_objective,
                "type": "user_intent",
                "is_business_fact": False,
                "is_approval": False,
                "is_execution_permit": False,
            },
            "store_ref": normalized_store_ref,
            "status": (
                "needs_evidence"
                if any(item["status"] != "verified" for item in missions)
                else "ready_for_human_review"
            ),
            "intent": intent,
            "source_snapshots": {
                "operating_analytics": analytics["snapshot_sha256"],
                "operating_workbench": workbench["snapshot_sha256"],
                "source_as_of": analytics.get("source_as_of"),
            },
            "truth_ledger": {
                "verified_facts": verified_facts,
                "unknowns": unknowns,
                "synthetic_business_data_allowed": False,
            },
            "missions": missions,
            "agent_team": [
                {
                    **agent,
                    "selected_for_objective": agent["agent_id"] in agent_ids,
                }
                for agent in workbench["agents"]
            ],
            "control_envelope": {
                "plan_only": True,
                "human_decision_required": True,
                "external_write_allowed": False,
                "automatic_execution": False,
                "objective_can_promote_fact": False,
                "model_output_can_promote_fact": False,
                "approval_and_execution_separate": True,
                "forbidden_actions": list(self.FORBIDDEN_ACTIONS),
                "continuation_rule": (
                    "只导航到既有 KJDS 工作区补证、复核或建立正式决策；"
                    "任何副作用继续使用既有审批、一次性许可、回读和回滚链。"
                ),
            },
        }
        payload["plan_sha256"] = self._hash(payload)
        return payload

    def _interpret_intent(self, objective: str) -> dict[str, Any]:
        normalized = objective.casefold()
        ranked = []
        for intent in self.INTENTS:
            matches = [
                keyword
                for keyword in intent["keywords"]
                if keyword.casefold() in normalized
            ]
            ranked.append((len(matches), intent, matches))
        score, selected, matches = max(ranked, key=lambda item: item[0])
        if score == 0:
            selected = self.DEFAULT_INTENT
        return {
            "id": selected["id"],
            "label": selected["label"],
            "interpretation": (
                f"将目标解释为“{selected['label']}”任务排序偏好"
                if score
                else "未检测到专用领域词，按完整经营就绪度排序"
            ),
            "matched_signals": matches,
            "rule_match_count": score,
            "inference_only": True,
            "changes_business_fact": False,
        }

    def _missions(
        self,
        *,
        analytics: dict[str, Any],
        workbench: dict[str, Any],
        intent: dict[str, Any],
    ) -> list[dict[str, Any]]:
        selected = next(
            (item for item in self.INTENTS if item["id"] == intent["id"]),
            self.DEFAULT_INTENT,
        )
        relevant_stage_ids = set(selected["stage_ids"])
        relevant_workspaces = set(selected["workspaces"])
        work_items = workbench["work_items"]

        stages = sorted(
            analytics["stages"],
            key=lambda stage: (
                0
                if stage["id"] in relevant_stage_ids
                or stage["workspace"] in relevant_workspaces
                else 1,
                0 if stage["status"] in {"blocked", "no_data"} else 1,
                stage["step"],
            ),
        )
        selected_stages = [
            stage for stage in stages if stage["status"] != "verified"
        ][:6]
        if not selected_stages:
            selected_stages = stages[:3]

        missions = []
        for rank, stage in enumerate(selected_stages, start=1):
            work_item = self._matching_work_item(stage, work_items)
            agent_id, agent_name = self.WORKSPACE_AGENTS.get(
                stage["workspace"],
                ("digital_ceo", "Digital CEO"),
            )
            if work_item:
                agent_id = work_item["agent_id"]
                agent_name = work_item["agent_name"]
            source_ids = list(
                dict.fromkeys(
                    [
                        *stage["source_ids"],
                        *(
                            [work_item["source_id"]]
                            if work_item and work_item.get("source_id")
                            else []
                        ),
                        *(work_item.get("evidence_ids", []) if work_item else []),
                    ]
                )
            )
            missions.append(
                {
                    "id": f"mission:{stage['id']}",
                    "rank": rank,
                    "stage_id": stage["id"],
                    "stage_step": stage["step"],
                    "title": stage["label"],
                    "status": stage["status"],
                    "objective_relevant": (
                        stage["id"] in relevant_stage_ids
                        or stage["workspace"] in relevant_workspaces
                    ),
                    "rationale": (
                        f"该阶段直接影响当前“{intent['label']}”目标"
                        if stage["id"] in relevant_stage_ids
                        or stage["workspace"] in relevant_workspaces
                        else "完成更高优先级相关阶段后仍需补齐的经营前置条件"
                    ),
                    "agent": {"id": agent_id, "name": agent_name},
                    "workspace": stage["workspace"],
                    "progress": {
                        "current": stage["current"],
                        "target": stage["target"],
                        "percent": stage["progress_percent"],
                    },
                    "next_action": (
                        work_item["next_action"]
                        if work_item
                        else stage["next_action"]
                    ),
                    "verification_condition": (
                        f"服务端阶段 {stage['id']} 重新投影为 verified，"
                        f"且 current 达到 target（{stage['target']}）"
                    ),
                    "source_ids": source_ids,
                    "observed_facts": stage["facts"],
                    "human_required": True,
                    "automatic_execution": False,
                    "platform_write_allowed": False,
                }
            )
        return missions

    @staticmethod
    def _matching_work_item(
        stage: dict[str, Any], work_items: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        source_ids = set(stage["source_ids"])
        return next(
            (
                item
                for item in work_items
                if item.get("source_id") in source_ids
            ),
            None,
        )

    @staticmethod
    def _verified_facts(analytics: dict[str, Any]) -> list[dict[str, Any]]:
        summary = analytics["summary"]
        listing = analytics.get("focal_listing")
        listing_source_ids = (
            [listing["source_evidence_id"]]
            if listing and listing.get("source_evidence_id")
            else []
        )
        facts = [
            {
                "id": "catalog_items",
                "label": "Ozon 目录商品",
                "value": summary["catalog_items"],
                "unit": "商品",
                "fact_type": "verified_observation",
                "source_ids": listing_source_ids,
            },
            {
                "id": "available_stock",
                "label": "目录可售库存",
                "value": summary["available_stock"],
                "unit": "件",
                "fact_type": "verified_observation",
                "source_ids": listing_source_ids,
            },
            {
                "id": "formal_finance_entries",
                "label": "正式财务分录",
                "value": summary["formal_finance_entries"],
                "unit": "分录",
                "fact_type": "formal_fact_count",
                "source_ids": [],
            },
            {
                "id": "ready_execution_plans",
                "label": "可执行计划",
                "value": summary["ready_execution_plans"],
                "unit": "计划",
                "fact_type": "governed_object_count",
                "source_ids": [],
            },
        ]
        for stage in analytics["stages"]:
            if stage["status"] == "verified":
                facts.append(
                    {
                        "id": f"stage:{stage['id']}",
                        "label": stage["label"],
                        "value": stage["current"],
                        "unit": f"目标 {stage['target']}",
                        "fact_type": "verified_stage",
                        "source_ids": stage["source_ids"],
                    }
                )
        return facts

    @staticmethod
    def _unknowns(analytics: dict[str, Any]) -> list[dict[str, Any]]:
        unknowns = [
            {
                "id": f"coverage:{item['id']}",
                "label": item["label"],
                "reason": (
                    f"仅有 {item['current']}/{item['target']} {item['unit']}，"
                    "不足部分保持 unknown"
                ),
                "next_action": next(
                    (
                        stage["next_action"]
                        for stage in analytics["stages"]
                        if stage["id"] == item["id"]
                    ),
                    "进入对应工作区补充可复验证据",
                ),
                "synthetic_fill_allowed": False,
            }
            for item in analytics["coverage"]
            if item["current"] < item["target"]
        ]
        known_reasons = {item["reason"] for item in unknowns}
        for index, gap in enumerate(analytics["data_gaps"], start=1):
            if gap not in known_reasons:
                unknowns.append(
                    {
                        "id": f"data-gap:{index}",
                        "label": "经营数据缺口",
                        "reason": gap,
                        "next_action": gap,
                        "synthetic_fill_allowed": False,
                    }
                )
        return unknowns[:12]

    @staticmethod
    def _normalize_text(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _hash(payload: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode()
        ).hexdigest()

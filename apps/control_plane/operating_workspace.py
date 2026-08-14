from __future__ import annotations

import hashlib
import json
from collections import Counter
from copy import deepcopy
from typing import Any

from .security import Principal


class OperatingWorkspaceError(ValueError):
    """Raised when an operating workspace route cannot be resolved safely."""


class OperatingWorkspaceService:
    """Project one point, line, or surface into an evidence-aware workbench.

    This module is intentionally read-only. It combines the versioned capability
    contract with the existing operating analytics projection; it does not infer
    business completion from a capability's implementation status.
    """

    CONTRACT_ID = "kjds-cross-border-operating-workspace-v1"
    KIND_COLLECTIONS = {
        "points": "atomic_points",
        "lines": "value_streams",
        "surfaces": "operating_surfaces",
    }
    WORKSPACE_HREFS = {
        "overview": "/operating-intelligence#anomalies",
        "data": "/operating-intelligence#anomalies",
        "research": "/#research",
        "products": "/operating-intelligence#media",
        "sourcing": "/#sourcing",
        "growth": "/#growth",
        "batch": "/#batch",
        "finance": "/operating-intelligence#profit",
        "science": "/#science",
        "governance": "/#governance",
        "system": "/#system",
        "evidenceops": "/evidenceops",
    }
    WORKSPACE_LABELS = {
        "overview": "经营异常中心",
        "data": "数据异常中心",
        "research": "选品研究",
        "products": "图片与视频工作台",
        "sourcing": "1688 与供应链",
        "growth": "Ozon 增长",
        "batch": "批量机会挖掘",
        "finance": "真实利润驾驶舱",
        "science": "AI 决策与实验",
        "governance": "审批与执行",
        "system": "系统运行",
        "evidenceops": "EvidenceOps Copilot",
    }
    ANALYTICS_STAGE_BY_POINT = {
        "ozon_catalog_read": "catalog",
        "market_signal_inbox": "sku-000",
        "keyword_demand_clustering": "sku-000",
        "canonical_product_identity": "sku-001",
        "external_listing_identity_map": "catalog",
        "product_passport_assembly": "sku-002",
        "supplier_rfq_package": "sku-003",
        "supplier_quote_review": "sku-003",
        "three_offer_comparison": "sku-003",
        "media_delivery_manifest": "content",
        "video_delivery_manifest": "content",
        "listing_draft_generate": "content",
        "listing_policy_lint": "content",
        "listing_human_approval": "content",
        "advertising_diagnostic": "growth",
        "execution_permit": "execution",
        "ozon_listing_write": "execution",
        "order_ingest": "ozn-002",
        "delivery_monitor": "ozn-002",
        "return_case": "ozn-002",
        "finance_transaction_ingest": "fin-001",
        "settlement_match": "fin-001",
        "reconciliation_exception": "fin-001",
    }
    RUNTIME_STATUS_ORDER = {
        "blocked": 0,
        "no_data": 1,
        "in_progress": 2,
        "verified": 3,
        "contract_only": 4,
    }

    def __init__(self, *, capability_atlas, operating_analytics) -> None:
        self.capability_atlas = capability_atlas
        self.operating_analytics = operating_analytics

    def snapshot(
        self,
        *,
        kind: str,
        item_id: str,
        store_ref: str = "ozon-primary",
        principal: Principal | None = None,
        entity_scope: dict[str, Any] | None = None,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        resolved_kind = kind.strip().lower()
        resolved_id = item_id.strip()
        scope = store_ref.strip()
        if resolved_kind not in self.KIND_COLLECTIONS:
            raise OperatingWorkspaceError(
                "Operating workspace kind must be points, lines, or surfaces"
            )
        if (
            not resolved_id
            or len(resolved_id) > 160
            or not resolved_id.replace("_", "").replace("-", "").isalnum()
        ):
            raise OperatingWorkspaceError(
                "Operating workspace item_id is invalid"
            )
        if not scope or len(scope) > 160:
            raise OperatingWorkspaceError(
                "Operating workspace store_ref must be 1 to 160 characters"
            )

        atlas = self.capability_atlas.snapshot()
        context = (principal, entity_scope)
        if any(value is not None for value in context) or as_of is not None:
            if principal is None or entity_scope is None:
                raise OperatingWorkspaceError(
                    "Scoped operating workspace requires principal "
                    "and entity_scope"
                )
            analytics = self.operating_analytics.snapshot(
                store_ref=scope,
                principal=principal,
                entity_scope=entity_scope,
                as_of=as_of,
            )
        else:
            analytics = self.operating_analytics.snapshot(
                store_ref=scope
            )
        graph = atlas["operating_graph"]
        point_index = {item["id"]: item for item in graph["atomic_points"]}
        line_index = {item["id"]: item for item in graph["value_streams"]}
        surface_index = {
            item["id"]: item for item in graph["operating_surfaces"]
        }
        collection = {
            "points": point_index,
            "lines": line_index,
            "surfaces": surface_index,
        }[resolved_kind]
        node = collection.get(resolved_id)
        if node is None:
            raise OperatingWorkspaceError(
                f"Unknown operating workspace {resolved_kind}/{resolved_id}"
            )

        point_ids, line_ids, surface_ids = self._related_ids(
            kind=resolved_kind,
            node=node,
            points=point_index,
            lines=line_index,
            surfaces=surface_index,
        )
        stage_ids = self._primary_stage_ids(
            kind=resolved_kind,
            node=node,
            lines=line_index,
        )
        analytics_stage_index = {
            item["id"]: item for item in analytics.get("stages", [])
        }
        stages = [
            self._project_point(
                point=point_index[point_id],
                sequence=index,
                analytics_stage_index=analytics_stage_index,
            )
            for index, point_id in enumerate(stage_ids, start=1)
        ]
        workspace_ids = self._ordered_unique(
            point_index[point_id]["workspace_id"] for point_id in point_ids
        )
        domain_signals = [
            deepcopy(stage)
            for stage in analytics.get("stages", [])
            if stage.get("workspace") in workspace_ids
        ]
        domain_signals.sort(
            key=lambda stage: (
                self.RUNTIME_STATUS_ORDER.get(stage.get("status"), 99),
                str(stage.get("step", "")),
            )
        )
        actions = [
            {
                "id": f"open:{workspace_id}",
                "kind": "navigate",
                "label": f"进入{self.WORKSPACE_LABELS[workspace_id]}",
                "workspace_id": workspace_id,
                "href": self.WORKSPACE_HREFS[workspace_id],
                "external_write": False,
                "requires_human_for_side_effects": True,
            }
            for workspace_id in workspace_ids
        ]
        context = self._node_context(
            kind=resolved_kind,
            node=node,
            points=point_index,
            lines=line_index,
        )
        navigation = {
            "atlas_href": "/capability-atlas",
            "self_href": node["workspace"],
            "related_points": [
                {
                    "id": point_id,
                    "label": point_index[point_id]["label"],
                    "href": point_index[point_id]["workspace"],
                }
                for point_id in point_ids
            ],
            "related_lines": [
                {
                    "id": line_id,
                    "label": line_index[line_id]["label"],
                    "href": line_index[line_id]["workspace"],
                }
                for line_id in line_ids
            ],
            "related_surfaces": [
                {
                    "id": surface_id,
                    "label": surface_index[surface_id]["label"],
                    "href": surface_index[surface_id]["workspace"],
                }
                for surface_id in surface_ids
            ],
        }
        payload = {
            "contract_id": self.CONTRACT_ID,
            "kind": resolved_kind,
            "item_id": resolved_id,
            "store_ref": scope,
            "title": node["label"],
            "mission": node.get("mission") or node.get("objective", ""),
            "release_version": atlas["release_version"],
            "registry_version": atlas["registry_version"],
            "registry_sha256": atlas["registry_sha256"],
            "source_as_of": analytics.get("source_as_of"),
            "context": context,
            "stages": stages,
            "domain_signals": domain_signals,
            "live": {
                "status": analytics.get("status", "no_data"),
                "summary": deepcopy(analytics.get("summary", {})),
                "focal_listing": deepcopy(analytics.get("focal_listing")),
                "priority_items": deepcopy(
                    analytics.get("priority_items", [])[:5]
                ),
                "data_gaps": list(analytics.get("data_gaps", [])),
                "analytics_snapshot_sha256": analytics.get("snapshot_sha256"),
            },
            "counts": {
                "stages": len(stages),
                "related_points": len(point_ids),
                "related_lines": len(line_ids),
                "related_surfaces": len(surface_ids),
                "domain_signals": len(domain_signals),
                "contract_statuses": dict(
                    sorted(Counter(stage["contract_status"] for stage in stages).items())
                ),
                "runtime_statuses": dict(
                    sorted(Counter(stage["runtime_status"] for stage in stages).items())
                ),
            },
            "actions": actions,
            "navigation": navigation,
            "control_envelope": {
                "read_only": True,
                "external_write_allowed": False,
                "client_can_recalculate_runtime_status": False,
                "contract_status_is_runtime_fact": False,
                "missing_data_must_remain_visible": True,
                "linkfox_is_workflow_reference_only": True,
            },
        }
        payload["workspace_sha256"] = self._canonical_hash(payload)
        return payload

    def _project_point(
        self,
        *,
        point: dict[str, Any],
        sequence: int,
        analytics_stage_index: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        analytics_stage_id = self.ANALYTICS_STAGE_BY_POINT.get(point["id"])
        runtime = (
            analytics_stage_index.get(analytics_stage_id)
            if analytics_stage_id
            else None
        )
        return {
            "sequence": sequence,
            "id": point["id"],
            "label": point["label"],
            "objective": point["objective"],
            "business_object": point["business_object"],
            "operation_kind": point["operation_kind"],
            "contract_status": point["status"],
            "runtime_status": (
                runtime.get("status", "no_data") if runtime else "contract_only"
            ),
            "runtime_scope": (
                f"operating_analytics:{analytics_stage_id}"
                if runtime
                else "no_exact_runtime_projection"
            ),
            "facts": list(runtime.get("facts", [])) if runtime else [],
            "evidence_ids": list(runtime.get("source_ids", [])) if runtime else [],
            "current": runtime.get("current") if runtime else None,
            "target": runtime.get("target") if runtime else None,
            "progress_percent": runtime.get("progress_percent") if runtime else None,
            "next_action": (
                runtime.get("next_action")
                if runtime
                else (
                    f"进入{self.WORKSPACE_LABELS[point['workspace_id']]}，"
                    "补齐真实对象与 Evidence 后再判断运行状态"
                )
            ),
            "input_contract": list(point["input_contract"]),
            "output_contract": list(point["output_contract"]),
            "evidence_gate": point["evidence_gate"],
            "failure_queue": point["failure_queue"],
            "failure_modes": list(point["failure_modes"]),
            "readback": point["readback"],
            "owner": point["owner"],
            "reviewer": point["reviewer"],
            "kpi": list(point["kpi"]),
            "sla": point["sla"],
            "workspace_href": point["workspace"],
            "workspace_id": point["workspace_id"],
            "domain_href": self.WORKSPACE_HREFS[point["workspace_id"]],
        }

    @staticmethod
    def _primary_stage_ids(
        *,
        kind: str,
        node: dict[str, Any],
        lines: dict[str, dict[str, Any]],
    ) -> list[str]:
        if kind == "points":
            return [node["id"]]
        if kind == "lines":
            return list(node["stage_point_ids"])
        ordered: list[str] = []
        for line_id in node["value_stream_ids"]:
            for point_id in lines[line_id]["stage_point_ids"]:
                if point_id not in ordered:
                    ordered.append(point_id)
        for point_id in node["focus_point_ids"]:
            if point_id not in ordered:
                ordered.append(point_id)
        return ordered

    @staticmethod
    def _related_ids(
        *,
        kind: str,
        node: dict[str, Any],
        points: dict[str, dict[str, Any]],
        lines: dict[str, dict[str, Any]],
        surfaces: dict[str, dict[str, Any]],
    ) -> tuple[list[str], list[str], list[str]]:
        if kind == "points":
            point_ids = [node["id"]]
            line_ids = list(node["value_stream_ids"])
        elif kind == "lines":
            point_ids = OperatingWorkspaceService._ordered_unique(
                [*node["stage_point_ids"], *node["supporting_point_ids"]]
            )
            line_ids = [node["id"]]
        else:
            line_ids = list(node["value_stream_ids"])
            point_ids = OperatingWorkspaceService._ordered_unique(
                [
                    *node["focus_point_ids"],
                    *(
                        point_id
                        for line_id in line_ids
                        for point_id in lines[line_id]["stage_point_ids"]
                    ),
                ]
            )
        surface_ids = [
            surface["id"]
            for surface in surfaces.values()
            if set(line_ids) & set(surface["value_stream_ids"])
            or set(point_ids) & set(surface["focus_point_ids"])
        ]
        return point_ids, line_ids, surface_ids

    @staticmethod
    def _node_context(
        *,
        kind: str,
        node: dict[str, Any],
        points: dict[str, dict[str, Any]],
        lines: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        if kind == "points":
            return {
                "type": "point",
                "business_object": node["business_object"],
                "operation_kind": node["operation_kind"],
                "contract_status": node["status"],
                "source_kind": node["source_kind"],
                "evidence_tier": node["evidence_tier"],
                "source_boundary": node["source_boundary"],
                "technology": node["technology"],
                "controls": list(node["controls"]),
                "markets": list(node["markets"]),
                "platforms": list(node["platforms"]),
            }
        if kind == "lines":
            return {
                "type": "line",
                "entry_gate": node["entry_gate"],
                "exit_gate": node["exit_gate"],
                "object_transitions": list(node["object_transitions"]),
                "events": list(node["events"]),
                "exceptions": list(node["exceptions"]),
                "human_takeover": node["human_takeover"],
                "kpi": list(node["kpi"]),
                "sla": node["sla"],
                "adapter_boundary": node["adapter_boundary"],
                "supporting_points": [
                    {
                        "id": point_id,
                        "label": points[point_id]["label"],
                        "href": points[point_id]["workspace"],
                    }
                    for point_id in node["supporting_point_ids"]
                ],
            }
        return {
            "type": "surface",
            "dimensions": list(node["dimensions"]),
            "decisions": list(node["decisions"]),
            "truth_owner": node["truth_owner"],
            "kpi": list(node["kpi"]),
            "alerts": list(node["alerts"]),
            "write_boundary": node["write_boundary"],
            "lines": [
                {
                    "id": line_id,
                    "label": lines[line_id]["label"],
                    "href": lines[line_id]["workspace"],
                }
                for line_id in node["value_stream_ids"]
            ],
        }

    @staticmethod
    def _ordered_unique(values) -> list[str]:
        return list(dict.fromkeys(values))

    @staticmethod
    def _canonical_hash(payload: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode()
        ).hexdigest()

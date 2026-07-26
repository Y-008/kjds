from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any


class OperatingAnalyticsService:
    """Project governed operating facts into one chart-ready, read-only snapshot."""

    CONTRACT_ID = "kjds-operating-flow-analytics-v1"

    def __init__(
        self,
        *,
        readiness,
        operating_workbench,
        marketplace_catalog,
        marketplace_growth,
        supplier_rfq,
        supplier_rfq_dispatch,
        procurement,
        execution_plans,
        post_execution,
        finance,
        product_media,
    ) -> None:
        self.readiness = readiness
        self.operating_workbench = operating_workbench
        self.marketplace_catalog = marketplace_catalog
        self.marketplace_growth = marketplace_growth
        self.supplier_rfq = supplier_rfq
        self.supplier_rfq_dispatch = supplier_rfq_dispatch
        self.procurement = procurement
        self.execution_plans = execution_plans
        self.post_execution = post_execution
        self.finance = finance
        self.product_media = product_media

    def snapshot(self, *, store_ref: str = "ozon-primary") -> dict[str, Any]:
        scope = store_ref.strip()
        if not scope or len(scope) > 160:
            raise ValueError("Operating analytics store_ref must be 1 to 160 characters")

        readiness = self.readiness.report()
        workbench = self.operating_workbench.snapshot(limit=100)
        catalog = self.marketplace_catalog.latest_items(store_ref=scope, limit=100)
        growth = self.marketplace_growth.latest_observations(limit=500)
        rfq_packages = self.supplier_rfq.list(limit=500)
        rfq_dispatches = self.supplier_rfq_dispatch.list(limit=500)
        sample_orders = self.procurement.list_orders(limit=500)
        execution_plans = self.execution_plans.list()
        observation_windows = self.post_execution.list_windows()
        finance_entries = self.finance.list_entries()

        requirements = {
            item["id"]: item for item in readiness.get("requirements", [])
        }
        products = readiness.get("products", [])
        bound_catalog = [
            item for item in catalog if item.get("canonical_product_id")
        ]
        media_readiness = self._media_readiness(bound_catalog)
        focal_listing = self._focal_listing(
            catalog=catalog,
            products=products,
            growth=growth,
            media_readiness=media_readiness,
        )
        accepted_dispatches = sum(
            item.get("status") == "accepted" for item in rfq_dispatches
        )
        ready_execution_plans = sum(
            bool(item.get("ready_for_executor")) for item in execution_plans
        )
        growth_sku_count = len(
            {
                item.get("marketplace_sku")
                for item in growth
                if item.get("marketplace_sku")
            }
        )
        approved_media_roles = sum(
            int(item.get("approved_role_count", 0)) for item in media_readiness.values()
        )
        required_media_roles = sum(
            len(item.get("required_roles", [])) for item in media_readiness.values()
        )

        stages = [
            self._object_stage(
                stage_id="catalog",
                step="01",
                label="Ozon 店铺同步",
                workspace="growth",
                current=len(catalog),
                target=1,
                source_ids=[item["source_evidence_id"] for item in catalog],
                next_action=(
                    "核对已同步 Listing、库存、价格和媒体引用"
                    if catalog
                    else "完成 Ozon 只读商品响应并导入可复验目录"
                ),
                facts=[
                    f"{len(catalog)} 个目录商品",
                    f"{len(bound_catalog)} 个已绑定运营档案",
                ],
            ),
            self._requirement_stage(
                requirements,
                requirement_id="SKU-000",
                step="02",
                label="需求与市场证据",
                workspace="research",
            ),
            self._requirement_stage(
                requirements,
                requirement_id="SKU-001",
                step="03",
                label="候选与商品立项",
                workspace="research",
            ),
            self._requirement_stage(
                requirements,
                requirement_id="SKU-002",
                step="04",
                label="商品 / 合规 / 质量",
                workspace="products",
            ),
            self._requirement_stage(
                requirements,
                requirement_id="SKU-003",
                step="05",
                label="三报价与供应链",
                workspace="sourcing",
                facts=[
                    f"{len(rfq_packages)} 份冻结 RFQ",
                    f"{len(rfq_dispatches)} 份发送证明 / {accepted_dispatches} 份已核验",
                ],
                source_ids=[
                    *[
                        item["evidence"].id
                        for item in rfq_packages
                        if item.get("evidence") is not None
                    ],
                    *[
                        item["evidence"].id
                        for item in rfq_dispatches
                        if item.get("evidence") is not None
                    ],
                ],
            ),
            self._object_stage(
                stage_id="content",
                step="06",
                label="内容与俄语 Listing",
                workspace="products",
                current=approved_media_roles,
                target=max(required_media_roles, 7 if bound_catalog else 1),
                source_ids=[],
                next_action=(
                    "补齐七类有权原图、三类 Passport、俄语内容 QA 与独立审批"
                    if bound_catalog
                    else "先建立 Canonical Product，再进入有权内容生产"
                ),
                facts=[
                    f"{sum(len(item.get('image_references', [])) for item in catalog)} 个外部图片引用",
                    f"{sum(len(item.get('video_references', [])) for item in catalog)} 个外部视频引用",
                    "外部媒体均未核权",
                ],
            ),
            self._object_stage(
                stage_id="growth",
                step="07",
                label="价格 / 内容 / 广告实验",
                workspace="growth",
                current=growth_sku_count,
                target=max(len(bound_catalog), 1),
                source_ids=self._flatten(
                    item.get("evidence_ids", []) for item in growth
                ),
                next_action=(
                    "用同行价格、真实转化率和完整 CM3 保存首个增长快照"
                    if not growth
                    else "复核组合建议并把动作送入有上限的审批实验"
                ),
                facts=[
                    f"{growth_sku_count} 个 SKU 有增长快照",
                    "自动改价与自动投放关闭",
                ],
            ),
            self._object_stage(
                stage_id="execution",
                step="08",
                label="审批与受控执行",
                workspace="governance",
                current=ready_execution_plans,
                target=1,
                source_ids=self._flatten(
                    item.get("evidence_ids", []) for item in execution_plans
                ),
                next_action=(
                    "等待上游证据和双人审批，不创建快捷平台写入"
                    if not ready_execution_plans
                    else "按一次性许可执行，并完成回读、观察和回滚准备"
                ),
                facts=[
                    f"{len(execution_plans)} 个执行计划",
                    f"{len(observation_windows)} 个执行后观察窗口",
                ],
            ),
            self._requirement_stage(
                requirements,
                requirement_id="OZN-002",
                step="09",
                label="订单 / 退货 / 结算",
                workspace="finance",
                facts=[
                    f"{len(sample_orders)} 个样品采购单",
                    f"{len(finance_entries)} 条正式财务分录",
                ],
            ),
            self._requirement_stage(
                requirements,
                requirement_id="FIN-001",
                step="10",
                label="利润 / FX / 对账",
                workspace="finance",
            ),
        ]

        coverage = [
            self._coverage(
                "official_catalog",
                "店铺目录",
                len(catalog),
                1,
                "Ozon 目录原件",
            ),
            self._coverage_from_requirement(
                requirements, "SKU-000", "需求权威", "需求报告"
            ),
            self._coverage_from_requirement(
                requirements, "SKU-002", "商品治理", "三类 Passport"
            ),
            self._coverage_from_requirement(
                requirements, "SKU-003", "供应链经济性", "三报价 + 正 CM3"
            ),
            self._coverage(
                "content_rights",
                "内容权利",
                approved_media_roles,
                max(required_media_roles, 7 if bound_catalog else 1),
                "有权原图角色",
            ),
            self._coverage(
                "growth_truth",
                "增长真源",
                growth_sku_count,
                max(len(bound_catalog), 1),
                "有证据增长快照",
            ),
            self._coverage_from_requirement(
                requirements, "OZN-001", "账户与权限", "账户/收款路径"
            ),
            self._combined_coverage(
                "finance_truth",
                "财务与结算",
                requirements,
                ("OZN-002", "FIN-001"),
                "五类 Ozon 事实 + 费用/FX",
            ),
        ]

        pipeline = [
            self._pipeline_item("catalog", "店铺目录", len(catalog), "商品"),
            self._pipeline_item(
                "bound", "已绑定运营档案", len(bound_catalog), "商品"
            ),
            self._pipeline_item(
                "growth", "有增长快照", growth_sku_count, "SKU"
            ),
            self._pipeline_item(
                "rfq", "已冻结 RFQ", len(rfq_packages), "包"
            ),
            self._pipeline_item(
                "dispatch", "已核验发送证明", accepted_dispatches, "证明"
            ),
            self._pipeline_item(
                "execution", "可执行计划", ready_execution_plans, "计划"
            ),
            self._pipeline_item(
                "observation", "执行后观察", len(observation_windows), "窗口"
            ),
            self._pipeline_item(
                "finance", "正式财务分录", len(finance_entries), "分录"
            ),
        ]

        payload = {
            "contract_id": self.CONTRACT_ID,
            "store_ref": scope,
            "status": readiness["status"],
            "source_as_of": self._latest_timestamp(catalog, growth),
            "summary": {
                "catalog_items": len(catalog),
                "bound_listings": len(bound_catalog),
                "available_stock": sum(
                    int(item.get("available_stock") or 0) for item in catalog
                ),
                "external_image_references": sum(
                    len(item.get("image_references", [])) for item in catalog
                ),
                "external_video_references": sum(
                    len(item.get("video_references", [])) for item in catalog
                ),
                "gate_blockers": readiness["exception_workspace"][
                    "blocked_count"
                ],
                "growth_snapshot_skus": growth_sku_count,
                "rfq_packages": len(rfq_packages),
                "verified_dispatch_proofs": accepted_dispatches,
                "formal_finance_entries": len(finance_entries),
                "ready_execution_plans": ready_execution_plans,
            },
            "recommended_playbook": self._recommended_playbook(
                catalog=catalog,
                bound_catalog=bound_catalog,
                growth=growth,
                requirements=requirements,
            ),
            "focal_listing": focal_listing,
            "stages": stages,
            "coverage": coverage,
            "pipeline": pipeline,
            "priority_items": workbench["work_items"][:5],
            "data_gaps": [
                item["next_action"]
                for item in readiness["exception_workspace"]["items"]
            ],
            "guardrails": {
                "advisory_only": True,
                "browser_gate_recalculation": False,
                "synthetic_business_data_allowed": False,
                "automatic_product_selection": False,
                "automatic_supplier_contact": False,
                "automatic_procurement": False,
                "automatic_pricing": False,
                "automatic_listing": False,
                "automatic_ad_spend": False,
                "platform_write_allowed": False,
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

    def _media_readiness(
        self, bound_catalog: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for item in bound_catalog:
            product_id = item.get("canonical_product_id")
            if product_id and product_id not in result:
                result[product_id] = self.product_media.readiness(product_id)
        return result

    def _focal_listing(
        self,
        *,
        catalog: list[dict[str, Any]],
        products: list[dict[str, Any]],
        growth: list[dict[str, Any]],
        media_readiness: dict[str, dict[str, Any]],
    ) -> dict[str, Any] | None:
        if not catalog:
            return None
        item = sorted(
            catalog,
            key=lambda row: (
                0 if row.get("canonical_product_id") else 1,
                str(row.get("offer_id", "")),
            ),
        )[0]
        product_id = item.get("canonical_product_id")
        readiness = next(
            (
                row
                for row in products
                if row.get("product", {}).get("id") == product_id
            ),
            None,
        )
        observation = next(
            (
                row
                for row in growth
                if str(row.get("marketplace_sku"))
                == str(item.get("marketplace_sku"))
            ),
            None,
        )
        status = item.get("statuses", {}).get("statuses", {})
        media = media_readiness.get(product_id or "", {})
        prices = item.get("prices", {})
        return {
            "offer_id": item["offer_id"],
            "marketplace_sku": item.get("marketplace_sku"),
            "canonical_product_id": product_id,
            "name": item.get("name", ""),
            "currency_code": item.get("currency_code"),
            "price": self._price(prices, "price"),
            "min_price": self._price(prices, "min_price"),
            "old_price": self._price(prices, "old_price"),
            "available_stock": item.get("available_stock"),
            "status": status.get("status"),
            "status_name": status.get("status_name"),
            "moderation_status": status.get("moderate_status"),
            "observed_at": item.get("observed_at"),
            "source_evidence_id": item.get("source_evidence_id"),
            "item_hash": item.get("item_hash"),
            "image_references": item.get("image_references", [])[:6],
            "video_reference_count": len(item.get("video_references", [])),
            "image_reference_count": len(item.get("image_references", [])),
            "document_reference_count": len(
                item.get("document_references", [])
            ),
            "media_rights_status": item.get("media_rights_status"),
            "approved_media_roles": media.get("approved_role_count", 0),
            "required_media_roles": len(media.get("required_roles", [])),
            "passports_ready": (
                readiness.get("passports_ready") if readiness else False
            ),
            "supplier_count": (
                readiness.get("supplier_count") if readiness else 0
            ),
            "complete_profit_scenario_count": (
                readiness.get("complete_profit_scenario_count")
                if readiness
                else 0
            ),
            "growth_observation": (
                {
                    "content_score": observation.get("content_score"),
                    "rating": observation.get("rating"),
                    "review_count": observation.get("review_count"),
                    "orders_14d": observation.get("orders_14d"),
                    "conversion_rate": observation.get("conversion_rate"),
                    "competitor_count": len(
                        observation.get("competitor_prices_rub", [])
                    ),
                    "observed_at": observation.get("observed_at"),
                }
                if observation
                else None
            ),
        }

    @staticmethod
    def _price(prices: dict[str, Any], key: str) -> str | None:
        value = prices.get(key)
        if value is None or isinstance(value, (dict, list)):
            return None
        text = str(value).strip()
        return text or None

    def _requirement_stage(
        self,
        requirements: dict[str, dict[str, Any]],
        *,
        requirement_id: str,
        step: str,
        label: str,
        workspace: str,
        facts: list[str] | None = None,
        source_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        requirement = requirements.get(requirement_id)
        if requirement is None:
            return self._stage(
                stage_id=requirement_id.lower(),
                step=step,
                label=label,
                workspace=workspace,
                status="no_data",
                current=0,
                target=1,
                next_action=f"等待 {requirement_id} 服务端 Readiness",
                source_ids=source_ids or [],
                facts=facts or [],
            )
        return self._stage(
            stage_id=requirement_id.lower(),
            step=step,
            label=label,
            workspace=workspace,
            status=(
                "verified"
                if requirement["ready"]
                else "in_progress"
                if requirement["current"] > 0
                else "blocked"
            ),
            current=requirement["current"],
            target=requirement["target"],
            next_action=requirement["next_action"],
            source_ids=[
                requirement_id,
                *(source_ids or []),
            ],
            facts=facts or [],
        )

    def _object_stage(
        self,
        *,
        stage_id: str,
        step: str,
        label: str,
        workspace: str,
        current: int,
        target: int,
        next_action: str,
        source_ids: list[str],
        facts: list[str],
    ) -> dict[str, Any]:
        return self._stage(
            stage_id=stage_id,
            step=step,
            label=label,
            workspace=workspace,
            status=(
                "verified"
                if current >= target
                else "in_progress"
                if current > 0
                else "no_data"
            ),
            current=current,
            target=target,
            next_action=next_action,
            source_ids=source_ids,
            facts=facts,
        )

    @staticmethod
    def _stage(
        *,
        stage_id: str,
        step: str,
        label: str,
        workspace: str,
        status: str,
        current: int,
        target: int,
        next_action: str,
        source_ids: list[str],
        facts: list[str],
    ) -> dict[str, Any]:
        return {
            "id": stage_id,
            "step": step,
            "label": label,
            "workspace": workspace,
            "status": status,
            "current": current,
            "target": target,
            "progress_percent": OperatingAnalyticsService._percent(
                current, target
            ),
            "next_action": next_action,
            "source_ids": list(dict.fromkeys(source_ids)),
            "facts": facts,
        }

    @staticmethod
    def _coverage(
        coverage_id: str,
        label: str,
        current: int,
        target: int,
        unit: str,
    ) -> dict[str, Any]:
        return {
            "id": coverage_id,
            "label": label,
            "current": current,
            "target": target,
            "percent": OperatingAnalyticsService._percent(current, target),
            "unit": unit,
        }

    def _coverage_from_requirement(
        self,
        requirements: dict[str, dict[str, Any]],
        requirement_id: str,
        label: str,
        unit: str,
    ) -> dict[str, Any]:
        requirement = requirements.get(requirement_id, {})
        return self._coverage(
            requirement_id.lower(),
            label,
            int(requirement.get("current", 0)),
            int(requirement.get("target", 1)),
            unit,
        )

    def _combined_coverage(
        self,
        coverage_id: str,
        label: str,
        requirements: dict[str, dict[str, Any]],
        requirement_ids: tuple[str, ...],
        unit: str,
    ) -> dict[str, Any]:
        current = sum(
            int(requirements.get(requirement_id, {}).get("current", 0))
            for requirement_id in requirement_ids
        )
        target = sum(
            int(requirements.get(requirement_id, {}).get("target", 1))
            for requirement_id in requirement_ids
        )
        return self._coverage(coverage_id, label, current, target, unit)

    @staticmethod
    def _pipeline_item(
        item_id: str, label: str, value: int, unit: str
    ) -> dict[str, Any]:
        return {"id": item_id, "label": label, "value": value, "unit": unit}

    @staticmethod
    def _percent(current: int, target: int) -> int:
        if target <= 0:
            return 0
        return min(100, max(0, round(current / target * 100)))

    @staticmethod
    def _flatten(values: Iterable[Iterable[str]]) -> list[str]:
        return list(dict.fromkeys(item for value in values for item in value))

    @staticmethod
    def _latest_timestamp(
        catalog: list[dict[str, Any]], growth: list[dict[str, Any]]
    ) -> str | None:
        timestamps = [
            str(value)
            for value in [
                *[item.get("observed_at") for item in catalog],
                *[item.get("observed_at") for item in growth],
            ]
            if value
        ]
        return max(timestamps) if timestamps else None

    @staticmethod
    def _recommended_playbook(
        *,
        catalog: list[dict[str, Any]],
        bound_catalog: list[dict[str, Any]],
        growth: list[dict[str, Any]],
        requirements: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        if bound_catalog:
            mode_id = "existing_listing_refinement"
            label = "现有店精细化修复"
            reasons = [
                f"已有 {len(bound_catalog)} 个绑定 Listing，可直接从真实商品事实诊断",
                (
                    "尚无有证据增长快照，先补同行价格、转化率和 CM3"
                    if not growth
                    else "已有增长快照，可进入有上限的组合实验"
                ),
            ]
        elif catalog:
            mode_id = "catalog_governance"
            label = "目录治理与运营建档"
            reasons = [
                f"已同步 {len(catalog)} 个 Listing，但尚未建立 Canonical Product 绑定",
                "先认领真实商品，再选择铺货、精细化或品牌策略",
            ]
        else:
            mode_id = "guided_foundation"
            label = "新手证据引导"
            reasons = [
                "尚无可复验店铺目录",
                "先完成账户、需求和只读数据基线",
            ]
        if not requirements.get("OZN-001", {}).get("ready", False):
            reasons.append("Ozon 账户、权限与收款路径仍未通过 Gate")
        return {
            "id": mode_id,
            "label": label,
            "reasons": reasons,
            "advisory_only": True,
            "automatic_mode_switch": False,
        }

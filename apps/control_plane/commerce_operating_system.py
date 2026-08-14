from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .security import Principal

CONTRACT_VERSION = "commerce-operating-system/1.0.0"
REGISTRY_PATH = Path(__file__).parents[2] / "docs" / "project" / "registries" / "competitive_capability_patterns.json"
MAOZI_BENCHMARK_PATH = (
    Path(__file__).parents[2] / "docs" / "project" / "registries" / "maozierp_feishu_capability_benchmark.json"
)


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


def _count(values: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = values.get(key)
        if isinstance(value, int):
            return value
    return 0


class CommerceOperatingSystem:
    """Project one governed operating system from existing domain authorities."""

    STAGES = (
        (
            "observe",
            "市场观察",
            "market_radar",
            "market_research",
            24,
            "/?workspace=batch",
            "采集带来源、时间、价格语义和 Evidence 的 Ozon/1688 观察",
        ),
        (
            "identity",
            "精确商品与变体",
            "product_identity",
            "product_data",
            24,
            "/?workspace=batch",
            "补齐精确商品身份、变体、MOQ 与跨市场同款证明",
        ),
        (
            "qualify",
            "十五项利润资格",
            "profit_pricing",
            "commerce_finance",
            48,
            "/?workspace=finance",
            "补齐 checkout、费率、物流、税、退货、FX 日期并重算下行 CM3",
        ),
        (
            "item_draft",
            "ERP 商品草稿",
            "catalog_sync",
            "catalog_operations",
            24,
            "/?workspace=batch",
            "从利润合格候选生成零库存 ERP Item 草稿并完成回读",
        ),
        (
            "content",
            "俄语内容与媒体",
            "content_media",
            "content_operations",
            72,
            "/?workspace=products",
            "用 Passport 和有权素材生成版本化草稿并完成内容/媒体 QA",
        ),
        (
            "listing_approval",
            "Listing 独立审批",
            "listing_operations",
            "independent_approver",
            24,
            "/?workspace=governance",
            "冻结 Listing 差异、利润底线和止损，交由独立身份审批",
        ),
        (
            "publish",
            "受控发布与回读",
            "listing_operations",
            "execution",
            1,
            "/?workspace=governance",
            "仅以一次性 Permit 执行并核对 Ozon Readback",
        ),
        (
            "order",
            "订单与售后",
            "order_fulfillment",
            "order_operations",
            1,
            "/?workspace=finance",
            "同步真实订单、取消、退货和客服事件并绑定同一商品",
        ),
        (
            "procurement_review",
            "出单后采购复核",
            "procurement",
            "procurement",
            4,
            "/?workspace=sourcing",
            "真实 awaiting_packaging 订单后复核库存、checkout 成本和时效",
        ),
        (
            "fulfill",
            "库存、物流与履约",
            "inventory_logistics",
            "fulfillment",
            4,
            "/?workspace=sourcing",
            "核对库存承诺、包裹重量、运单、节点和异常；不猜履约状态",
        ),
        (
            "settle",
            "平台结算",
            "settlement",
            "finance",
            72,
            "/operating-intelligence",
            "导入并复核订单日费率、平台应计、退货与结算原件",
        ),
        (
            "reconcile",
            "银行到账与现金 CM3",
            "settlement",
            "finance",
            72,
            "/operating-intelligence",
            "以结算、银行和 FX Evidence 对账，隔离所有未分摊差异",
        ),
        (
            "learn",
            "24h/72h/7d 学习",
            "experiment_learning",
            "experiment_science",
            168,
            "/?workspace=science",
            "用回读、退货和到账 CM3 更新策略；赢家才可扩量或裂变",
        ),
    )

    CAPABILITIES = (
        ("market_intelligence", "市场、竞品与机会", ("observe",)),
        ("exact_product_identity", "商品、SKU 与真实变体", ("identity",)),
        ("supplier_sourcing", "1688、供应商与报价", ("identity", "qualify")),
        ("profit_and_pricing", "十五项利润与定价", ("qualify",)),
        ("product_catalog", "商品库与 ERP Item", ("item_draft",)),
        ("content_and_media", "俄语内容、图片与视频", ("content",)),
        (
            "listing_management",
            "采集认领、批量编辑与刊登",
            ("content", "listing_approval", "publish"),
        ),
        ("orders_and_returns", "订单、取消、退货与客服", ("order",)),
        ("customer_service", "消息、纠纷与售后协同", ("order",)),
        ("procurement", "出单采购与供应协同", ("procurement_review",)),
        ("inventory", "库存、仓库与补货", ("fulfill",)),
        ("logistics", "打单、物流与履约跟踪", ("fulfill",)),
        ("ads_and_promotions", "广告、促销与价格实验", ("learn",)),
        ("finance_and_settlement", "费用、结算、到账与利润", ("settle", "reconcile")),
        ("operations_tasks", "批量任务、异常、重试与 Owner", ("observe", "learn")),
        ("team_governance", "多店、RBAC、Evidence 与审计", ("listing_approval",)),
        ("store_management", "多店铺、品牌和主体矩阵", ("listing_approval",)),
        ("ai_agent_team", "Agent Team 协作与学习", ("observe", "learn")),
    )

    BENCHMARK_CAPABILITIES = {
        "seerfar": {
            "market_intelligence",
            "exact_product_identity",
            "profit_and_pricing",
            "product_catalog",
            "content_and_media",
            "listing_management",
            "ads_and_promotions",
            "operations_tasks",
        },
        "selling51_erp": {
            "market_intelligence",
            "exact_product_identity",
            "supplier_sourcing",
            "profit_and_pricing",
            "product_catalog",
            "content_and_media",
            "listing_management",
            "orders_and_returns",
            "customer_service",
            "procurement",
            "inventory",
            "logistics",
            "finance_and_settlement",
            "operations_tasks",
        },
        "miaoshou_erp": {
            "market_intelligence",
            "exact_product_identity",
            "supplier_sourcing",
            "profit_and_pricing",
            "product_catalog",
            "content_and_media",
            "listing_management",
            "orders_and_returns",
            "procurement",
            "inventory",
            "logistics",
            "operations_tasks",
        },
        "mango_erp": {
            "market_intelligence",
            "exact_product_identity",
            "supplier_sourcing",
            "profit_and_pricing",
            "product_catalog",
            "content_and_media",
            "listing_management",
            "orders_and_returns",
            "procurement",
            "inventory",
            "logistics",
            "ads_and_promotions",
            "finance_and_settlement",
            "operations_tasks",
            "team_governance",
            "store_management",
        },
        "dianxiaomi_erp": {
            "market_intelligence",
            "exact_product_identity",
            "supplier_sourcing",
            "profit_and_pricing",
            "product_catalog",
            "content_and_media",
            "listing_management",
            "orders_and_returns",
            "customer_service",
            "procurement",
            "inventory",
            "logistics",
            "ads_and_promotions",
            "finance_and_settlement",
            "operations_tasks",
            "team_governance",
            "store_management",
        },
        "maozierp": {
            "market_intelligence",
            "exact_product_identity",
            "supplier_sourcing",
            "profit_and_pricing",
            "product_catalog",
            "content_and_media",
            "listing_management",
            "orders_and_returns",
            "inventory",
            "operations_tasks",
        },
        "lizhi_ozon_assistant": {
            "market_intelligence",
            "exact_product_identity",
            "profit_and_pricing",
            "product_catalog",
            "content_and_media",
            "operations_tasks",
            "ai_agent_team",
        },
        "linkfox": {
            "market_intelligence",
            "exact_product_identity",
            "product_catalog",
            "content_and_media",
            "listing_management",
            "operations_tasks",
            "team_governance",
            "ai_agent_team",
        },
    }

    AGENTS = (
        (
            "digital_ceo",
            "经营总控 Agent",
            ("observe", "qualify", "learn"),
            "portfolio_decision_packet",
            ("read_snapshots", "prioritize_internal_tasks"),
        ),
        (
            "market_radar",
            "市场雷达 Agent",
            ("observe",),
            "market_observation_cohort",
            ("read_allowed_sources", "normalize_observations"),
        ),
        (
            "product_identity",
            "商品身份 Agent",
            ("identity",),
            "exact_identity_diff",
            ("normalize_attributes", "detect_duplicates"),
        ),
        (
            "supplier_sourcing",
            "供应链 Agent",
            ("identity", "procurement_review"),
            "supplier_pareto_packet",
            ("compare_suppliers", "prepare_rfq_draft"),
        ),
        (
            "profit_pricing",
            "利润定价 Agent",
            ("qualify", "settle", "reconcile"),
            "cm3_and_cash_bridge",
            ("recalculate_decimal_ledger", "flag_unallocated"),
        ),
        (
            "catalog_sync",
            "商品库 Agent",
            ("item_draft",),
            "erp_item_draft_diff",
            ("prepare_zero_stock_draft", "compare_readback"),
        ),
        (
            "content_media",
            "内容媒体 Agent",
            ("content",),
            "versioned_listing_content_draft",
            ("draft_from_passport", "run_machine_qa"),
        ),
        (
            "listing_operations",
            "Listing Agent",
            ("listing_approval", "publish"),
            "frozen_listing_diff",
            ("prepare_listing_diff", "compare_platform_readback"),
        ),
        (
            "order_fulfillment",
            "订单履约 Agent",
            ("order", "fulfill"),
            "order_fulfillment_exception",
            ("normalize_orders", "detect_sla_exception"),
        ),
        (
            "inventory_logistics",
            "库存物流 Agent",
            ("fulfill",),
            "inventory_and_route_plan",
            ("calculate_replenishment_proposal", "compare_routes"),
        ),
        (
            "risk_compliance",
            "风险合规 Agent",
            ("identity", "listing_approval", "publish"),
            "passport_and_execution_gate",
            ("evaluate_rules", "engage_internal_blocker"),
        ),
        (
            "experiment_learning",
            "实验学习 Agent",
            ("learn",),
            "24h_72h_7d_learning_report",
            ("evaluate_experiment", "recommend_scale_or_stop"),
        ),
    )

    def __init__(
        self,
        *,
        truth_governance,
        batch_opportunity,
        profit_erp_sync,
        operating_analytics,
        operating_workbench,
        media_workbench,
        product_content=None,
        intelligence_source_adapters=None,
        scoped_ozon_imports=None,
        scoped_facts=None,
        scoped_read_only_pilots=None,
        scoped_read_only_claims=None,
        native_parity_acceptance=None,
        registry_path: Path = REGISTRY_PATH,
        maozierp_benchmark_path: Path = MAOZI_BENCHMARK_PATH,
    ) -> None:
        self.truth_governance = truth_governance
        self.batch_opportunity = batch_opportunity
        self.profit_erp_sync = profit_erp_sync
        self.operating_analytics = operating_analytics
        self.operating_workbench = operating_workbench
        self.media_workbench = media_workbench
        self.product_content = product_content
        self.intelligence_source_adapters = intelligence_source_adapters
        self.scoped_ozon_imports = scoped_ozon_imports
        self.scoped_facts = scoped_facts
        self.scoped_read_only_pilots = scoped_read_only_pilots
        self.scoped_read_only_claims = scoped_read_only_claims
        self.native_parity_acceptance = native_parity_acceptance
        self.registry_path = registry_path
        self.maozierp_benchmark_path = maozierp_benchmark_path

    def workspace(
        self,
        *,
        principal: Principal,
        store_ref: str,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        store = store_ref.strip()
        if not store:
            raise ValueError("store_ref is required")
        if not principal.can_access_store(store):
            raise PermissionError("Authenticated identity is not authorized for store_ref")
        cutoff = self._as_of(as_of)
        scope_truth = self.truth_governance.snapshot(
            principal=principal,
            store_ref=store,
            as_of=cutoff.isoformat(),
            evidence_ids=[],
        )
        entity_scope = scope_truth.get("scope", {}).get(
            "entity_scope",
            {
                "status": "no_data",
                "entity_ref": None,
                "authority_sha256": None,
            },
        )
        scope_ready = (
            entity_scope.get("status") == "ready"
            and entity_scope.get("entity_ref")
            and entity_scope.get("authority_sha256")
        )
        intelligence_sources = (
            self.intelligence_source_adapters.snapshot(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store,
                as_of=cutoff,
            )
            if callable(
                getattr(
                    self.intelligence_source_adapters,
                    "snapshot",
                    None,
                )
            )
            else self._unscoped_intelligence_sources(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store,
                as_of=cutoff,
            )
        )
        read_only_pilots = self._read_only_pilot_authority(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store,
            as_of=cutoff,
        )
        read_only_claims = self._read_only_claim_authority(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store,
            as_of=cutoff,
        )
        ozon_imports = self._ozon_import_authority(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store,
            as_of=cutoff,
        )
        formal_facts = self._formal_fact_authority(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store,
            as_of=cutoff,
        )
        has_market_radar = callable(getattr(self.batch_opportunity, "market_radar", None))
        market_radar = (
            self.batch_opportunity.market_radar(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store,
                as_of=cutoff,
                timezone="UTC",
                display_currency="CNY",
                source_grades=("A", "B", "C"),
                max_age_hours=168,
                target_purchase_quantity=3,
                page_size=500,
                max_rows=50000,
            )
            if scope_ready and has_market_radar
            else self._unscoped_market_radar(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store,
                as_of=cutoff,
            )
        )
        batch = (
            self.batch_opportunity.latest_scoped(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store,
                as_of=cutoff,
            )
            if scope_ready
            and callable(
                getattr(
                    self.batch_opportunity,
                    "latest_scoped",
                    None,
                )
            )
            else self._unscoped_batch(store)
        )
        product_content = (
            self.product_content.project(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store,
                as_of=cutoff,
            )
            if scope_ready
            and callable(
                getattr(
                    self.product_content,
                    "project",
                    None,
                )
            )
            else self._unscoped_product_content(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store,
                as_of=cutoff,
            )
        )
        erp = (
            self.profit_erp_sync.workspace_scoped(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store,
                as_of=cutoff.isoformat(),
            )
            if scope_ready
            and callable(
                getattr(
                    self.profit_erp_sync,
                    "workspace_scoped",
                    None,
                )
            )
            else self._unscoped_erp(
                tenant_ref=principal.tenant_ref,
                store_ref=store,
            )
        )
        analytics = self.operating_analytics.snapshot(
            store_ref=store,
            principal=principal,
            entity_scope=entity_scope,
            as_of=cutoff.isoformat(),
        )
        workbench = self.operating_workbench.snapshot(
            limit=100,
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store,
            as_of=cutoff.isoformat(),
        )
        media = (
            self.media_workbench.snapshot_scoped(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store,
                as_of=cutoff.isoformat(),
            )
            if scope_ready
            and callable(
                getattr(
                    self.media_workbench,
                    "snapshot_scoped",
                    None,
                )
            )
            else self._unscoped_media()
        )
        evidence_ids = self._batch_evidence_ids(batch)
        truth = (
            self.truth_governance.snapshot(
                principal=principal,
                store_ref=store,
                as_of=cutoff.isoformat(),
                evidence_ids=evidence_ids,
            )
            if evidence_ids
            else scope_truth
        )
        stages = self._stages(
            batch=batch,
            erp=erp,
            analytics=analytics,
            truth=truth,
            media=media,
        )
        native_parity = (
            self.native_parity_acceptance.project(
                principal=principal,
                entity_scope={
                    **entity_scope,
                    "tenant_ref": principal.tenant_ref,
                    "store_ref": store,
                },
                store_ref=store,
                as_of=cutoff,
                page_size=100,
            )
            if self.native_parity_acceptance is not None
            else self._unbound_native_parity(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store,
                as_of=cutoff,
            )
        )
        capabilities = self._capabilities(stages, native_parity)
        providers = self._benchmarks(capabilities, native_parity)
        baseline_registry = self._registry()
        benchmark_snapshot_sha256 = next(
            item["workflow_mapping"]["snapshot_sha256"]
            for item in providers
            if item["benchmark_id"] == "maozierp" and item["workflow_mapping"] is not None
        )
        agents = self._agents(
            stages=stages,
            workbench=workbench,
            source_hashes={
                "truth": truth.get("snapshot_sha256"),
                "intelligence_sources": intelligence_sources.get("snapshot_sha256"),
                "read_only_pilots": read_only_pilots.get("snapshot_sha256"),
                "read_only_claims": read_only_claims.get("snapshot_sha256"),
                "ozon_imports": ozon_imports.get("snapshot_sha256"),
                "formal_facts": formal_facts.get("snapshot_sha256"),
                "market_radar": market_radar.get("snapshot_sha256"),
                "batch": batch.get("snapshot_sha256"),
                "analytics": analytics.get("snapshot_sha256"),
                "workbench": workbench.get("snapshot_sha256"),
                "competitive_benchmarks": benchmark_snapshot_sha256,
                "market_validated_baseline": baseline_registry["snapshot_sha256"],
            },
        )
        completed = sum(item["status"] == "completed" for item in stages)
        current = next(
            (item for item in stages if item["status"] != "completed"),
            None,
        )
        payload = {
            "contract_version": CONTRACT_VERSION,
            "as_of": cutoff.isoformat(),
            "scope": {
                "tenant_ref": principal.tenant_ref,
                "entity_ref": truth.get("scope", {}).get("entity_scope", {}).get("entity_ref"),
                "store_ref": store,
                "actor_id": principal.actor_id,
                "roles": sorted(principal.roles),
            },
            "status": (
                "ready" if completed == len(stages) else "operating_with_constraints" if completed else "no_data"
            ),
            "outcome": {
                "observed_listings": _count(
                    (market_radar.get("counts", {}) if has_market_radar else batch.get("counts", {})),
                    "observed_listings",
                    "observed",
                ),
                "unique_exact_identities": _count(
                    (market_radar.get("counts", {}) if has_market_radar else batch.get("counts", {})),
                    "unique_exact_identities",
                ),
                "fully_costed_candidates": _count(batch.get("counts", {}), "fully_costed_candidates"),
                "downside_positive": _count(batch.get("counts", {}), "downside_positive"),
                "profit_qualified_for_erp": _count(erp.get("counts", {}), "profit_qualified"),
                "erp_item_sync_succeeded": _count(erp.get("counts", {}), "succeeded"),
                "published": _count(batch.get("counts", {}), "published"),
                "ordered": _count(batch.get("counts", {}), "ordered"),
                "settled_proven": _count(batch.get("counts", {}), "settled_proven"),
                "actual_profit_claimed": False,
            },
            "current_stage": (
                None
                if current is None
                else {
                    "id": current["id"],
                    "label": current["label"],
                    "status": current["status"],
                    "why": current["why"],
                    "owner": current["owner"],
                    "next_action": current["next_action"],
                    "workspace_href": current["workspace_href"],
                }
            ),
            "stages": stages,
            "capabilities": capabilities,
            "native_parity_acceptance": native_parity,
            "native_architecture": self._native_architecture(capabilities),
            "benchmark_baseline_policy": baseline_registry["baseline_policy"],
            "benchmark_coverage": providers,
            "ai_content_factory": {
                "status": media.get("status", "no_data"),
                "summary": media.get("summary", {}),
                "templates": media.get("templates", []),
                "control_envelope": media.get("control_envelope", {}),
                "truth_inputs": [
                    "Product Passport",
                    "Quality Passport",
                    "Compliance Passport",
                    "rights-cleared source assets",
                    "category attribute schema",
                ],
                "outputs": [
                    "main/detail/scene/infographic image drafts",
                    "9:16/1:1/16:9 video drafts",
                    "subtitles/covers/keyframes",
                    "QA report",
                    "Delivery Manifest",
                ],
                "competitor_asset_copy_allowed": False,
                "listing_reference_requires_all_qa_passed": True,
            },
            "intelligence_sources": intelligence_sources,
            "read_only_pilots": read_only_pilots,
            "read_only_claims": read_only_claims,
            "ozon_imports": ozon_imports,
            "formal_facts": formal_facts,
            "market_radar": market_radar,
            "product_content": product_content,
            "agent_team": agents,
            "source_snapshots": {
                "truth_governance": truth.get("snapshot_sha256"),
                "intelligence_sources": intelligence_sources.get("snapshot_sha256"),
                "read_only_pilots": read_only_pilots.get("snapshot_sha256"),
                "read_only_claims": read_only_claims.get("snapshot_sha256"),
                "ozon_imports": ozon_imports.get("snapshot_sha256"),
                "formal_facts": formal_facts.get("snapshot_sha256"),
                "market_radar": market_radar.get("snapshot_sha256"),
                "batch_opportunity": (batch.get("scoped_snapshot_sha256") or batch.get("snapshot_sha256")),
                "product_content": product_content.get("snapshot_sha256"),
                "profit_erp_sync": _hash(erp),
                "operating_analytics": analytics.get("snapshot_sha256"),
                "operating_workbench": workbench.get("snapshot_sha256"),
                "media_workbench": media.get("snapshot_sha256"),
                "native_parity_acceptance": native_parity.get("snapshot_sha256"),
                "competitive_benchmark_registry": self._registry()["snapshot_sha256"],
                "maozierp_workflow_benchmark": (self._maozierp_workflow_registry()["snapshot_sha256"]),
            },
            "source_gaps": sorted(
                set(
                    truth.get("source_gaps", [])
                    + intelligence_sources.get("source_gaps", [])
                    + read_only_pilots.get("source_gaps", [])
                    + read_only_claims.get("source_gaps", [])
                    + ozon_imports.get("source_gaps", [])
                    + formal_facts.get("source_gaps", [])
                    + market_radar.get("source_gaps", [])
                    + batch.get("blockers", [])
                    + product_content.get("source_gaps", [])
                    + erp.get("blockers", [])
                    + analytics.get("data_gaps", [])
                )
            ),
            "control_envelope": {
                "read_only_projection": True,
                "external_writes": False,
                "ozon_write": False,
                "supplier_message": False,
                "supplier_order": False,
                "purchase": False,
                "payment": False,
                "inventory_write": False,
                "price_write": False,
                "advertising_write": False,
                "agent_self_approval": False,
                "agent_permit_issuance": False,
                "captcha_bypass": False,
                "independent_approval_required": True,
                "one_time_permit_required": True,
                "readback_required": True,
                "kill_switch_required": True,
                "compensation_required": True,
            },
            "completion_claim": {
                "benchmark_business_flows_fully_covered": all(
                    item["coverage_status"] == "verified_parity" for item in providers
                ),
                "benchmark_products_are_runtime_dependencies": False,
                "real_profit_loop_complete": (_count(batch.get("counts", {}), "settled_proven") > 0),
                "automatic_listing_count_is_success_metric": False,
                "success_metric": ("reconciled cash CM3 + controlled learning + reversible execution"),
            },
        }
        payload["snapshot_sha256"] = _hash(payload)
        return payload

    def _formal_fact_authority(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        authority = self.scoped_facts
        ready = (
            entity_scope.get("status") == "ready"
            and entity_scope.get("entity_ref")
            and entity_scope.get("authority_sha256")
        )
        if ready and callable(getattr(authority, "list", None)):
            return authority.list(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                as_of=as_of,
                limit=100,
            )
        payload = {
            "contract_id": "kjds-native-scoped-formal-facts-v1",
            "status": "no_data",
            "scope": {
                "tenant_ref": principal.tenant_ref,
                "entity_ref": (str(entity_scope["entity_ref"]) if ready else None),
                "store_ref": store_ref,
                "scope_grant_authority_sha256": (str(entity_scope["authority_sha256"]) if ready else None),
            },
            "as_of": as_of.isoformat(),
            "items": [],
            "formal_fact_count": 0,
            "source_gaps": [
                (
                    "scoped_formal_fact_authority_missing"
                    if ready
                    else entity_scope.get(
                        "reason",
                        "entity_scope_authority_missing",
                    )
                )
            ],
            "legacy_rows_inferred": False,
            "claim_source_allowed": False,
            "accounting_posted": False,
            "external_write_allowed": False,
            "approval_created": False,
            "permit_created": False,
        }
        payload["snapshot_sha256"] = _hash(payload)
        return payload

    def _ozon_import_authority(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        authority = self.scoped_ozon_imports
        if callable(getattr(authority, "list", None)):
            return authority.list(
                principal=principal,
                entity_scope=entity_scope,
                store_ref=store_ref,
                as_of=as_of,
                limit=100,
            )
        payload = {
            "contract_id": "kjds-scoped-ozon-import-staging-v1",
            "status": "no_data",
            "scope": {
                "tenant_ref": principal.tenant_ref,
                "entity_ref": None,
                "store_ref": store_ref,
                "scope_grant_authority_sha256": None,
            },
            "items": [],
            "counts": {
                "imports": 0,
                "rows": 0,
                "accepted_rows": 0,
                "rejected_rows": 0,
            },
            "source_gaps": ["scoped_ozon_import_authority_missing"],
            "legacy_rows_inferred": False,
            "formal_fact_promotion_allowed": False,
            "external_write_allowed": False,
        }
        payload["snapshot_sha256"] = _hash(payload)
        return payload

    def _read_only_claim_authority(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        authority = self.scoped_read_only_claims
        if not callable(getattr(authority, "list", None)):
            payload = {
                "contract_id": "kjds-scoped-read-only-claims-v1",
                "status": "no_data",
                "scope": {
                    "tenant_ref": principal.tenant_ref,
                    "entity_ref": None,
                    "store_ref": store_ref,
                    "scope_grant_authority_sha256": None,
                },
                "counts": {
                    "claims": 0,
                    "pending_review": 0,
                    "accepted": 0,
                    "rejected": 0,
                    "authority_blocked": 0,
                },
                "source_gaps": ["scoped_read_only_claim_authority_missing"],
                "legacy_rows_inferred": False,
                "formal_fact_promoted": False,
                "external_write_allowed": False,
            }
            payload["snapshot_sha256"] = _hash(payload)
            return payload
        return authority.list(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
            limit=100,
        )

    def _read_only_pilot_authority(
        self,
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        authority = self.scoped_read_only_pilots
        if not callable(getattr(authority, "list", None)) or not callable(getattr(authority, "list_runs", None)):
            payload = {
                "contract_id": "kjds-scoped-read-only-pilots-v1",
                "status": "no_data",
                "scope": {
                    "tenant_ref": principal.tenant_ref,
                    "entity_ref": None,
                    "store_ref": store_ref,
                    "scope_grant_authority_sha256": None,
                },
                "counts": {"pilots": 0, "runs": 0},
                "source_gaps": ["scoped_read_only_pilot_authority_missing"],
                "legacy_rows_inferred": False,
                "external_write_allowed": False,
            }
            payload["snapshot_sha256"] = _hash(payload)
            return payload
        pilots = authority.list(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
            limit=100,
        )
        runs = authority.list_runs(
            principal=principal,
            entity_scope=entity_scope,
            store_ref=store_ref,
            as_of=as_of,
            limit=100,
        )
        payload = {
            "contract_id": authority.CONTRACT_ID,
            "status": (
                "ready"
                if pilots["items"] or runs["items"]
                else "blocked"
                if "blocked" in {pilots["status"], runs["status"]}
                else "no_data"
            ),
            "scope": pilots["scope"],
            "counts": {
                "pilots": len(pilots["items"]),
                "runs": len(runs["items"]),
            },
            "source_gaps": sorted(set(pilots.get("source_gaps", []) + runs.get("source_gaps", []))),
            "legacy_rows_inferred": False,
            "external_write_allowed": False,
        }
        payload["snapshot_sha256"] = _hash(payload)
        return payload

    @staticmethod
    def _unscoped_market_radar(
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        reason = (
            "entity_scope_authority_missing"
            if entity_scope.get("status") != "ready"
            else "scoped_market_radar_authority_missing"
        )
        payload = {
            "contract_id": "kjds-scoped-market-radar-v1",
            "status": "no_data",
            "as_of": as_of.isoformat(),
            "scope": {
                "tenant_ref": principal.tenant_ref,
                "entity_ref": None,
                "store_ref": store_ref,
                "scope_grant_authority_sha256": None,
            },
            "query": {
                "timezone": "UTC",
                "display_currency": "CNY",
                "source_grades": ["A", "B", "C"],
                "max_age_hours": 168,
                "target_purchase_quantity": 3,
                "currency_conversion_performed": False,
            },
            "counts": {
                "observed_listings": 0,
                "unique_exact_identities": 0,
                "own_listing_rows": 0,
                "competitor_listing_rows": 0,
                "unique_competitor_sellers": 0,
                "supplier_option_rows": 0,
                "unique_supplier_identities": 0,
                "checkout_comparable_at_target": 0,
                "unresolved_or_filtered_rows": 0,
            },
            "cohorts": [],
            "unresolved": {
                "count": 0,
                "details_disclosed": False,
                "by_reason": {},
            },
            "source_gaps": [reason],
            "blockers": [],
            "source_snapshots": {},
            "control_envelope": {
                "read_only": True,
                "research_only": True,
                "client_calculation_allowed": False,
                "candidate_scoring_performed": False,
                "sales_inferred": False,
                "supplier_offer_created": False,
                "actual_cost_created": False,
                "formal_cm3_created": False,
                "approval_created": False,
                "permit_created": False,
                "external_write_allowed": False,
            },
        }
        payload["snapshot_sha256"] = _hash(payload)
        return payload

    @staticmethod
    def _unscoped_intelligence_sources(
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        reason = (
            "entity_scope_authority_missing"
            if entity_scope.get("status") != "ready"
            else "intelligence_source_adapter_authority_missing"
        )
        payload = {
            "contract_id": ("kjds-intelligence-source-adapter-authority-v1"),
            "status": "no_data",
            "as_of": as_of.isoformat(),
            "scope": {
                "tenant_ref": principal.tenant_ref,
                "entity_ref": entity_scope.get("entity_ref"),
                "store_ref": store_ref,
                "scope_grant_authority_sha256": entity_scope.get("authority_sha256"),
            },
            "adapters": [],
            "counts": {
                "implemented": 0,
                "contract_only": 0,
                "external_write_enabled": 0,
            },
            "source_gaps": [reason],
            "control_envelope": {
                "capture_requires_current_entity_scope": True,
                "capture_requires_independent_evidence_binding": True,
                "supplier_offer_created": False,
                "actual_cost_created": False,
                "sales_fact_inferred": False,
                "external_write_allowed": False,
            },
        }
        payload["snapshot_sha256"] = _hash(payload)
        return payload

    @staticmethod
    def _unscoped_batch(store_ref: str) -> dict[str, Any]:
        return {
            "store_ref": store_ref,
            "state": "no_data",
            "counts": {},
            "candidates": [],
            "blockers": ["scoped_batch_authority_missing"],
            "snapshot_sha256": None,
            "evidence_id": None,
        }

    @staticmethod
    def _unscoped_erp(
        *,
        tenant_ref: str,
        store_ref: str,
    ) -> dict[str, Any]:
        return {
            "tenant_ref": tenant_ref,
            "store_ref": store_ref,
            "state": "no_data",
            "counts": {"profit_qualified": 0, "succeeded": 0},
            "connector": {"configured": False},
            "blockers": ["scoped_erp_item_authority_missing"],
            "syncs": [],
        }

    @staticmethod
    def _unscoped_product_content(
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        reason = (
            "entity_scope_authority_missing"
            if entity_scope.get("status") != "ready"
            else "scoped_product_content_authority_missing"
        )
        payload = {
            "contract_id": "kjds-scoped-product-content-v1",
            "status": "no_data",
            "as_of": as_of.isoformat(),
            "scope": {
                "tenant_ref": principal.tenant_ref,
                "entity_ref": entity_scope.get("entity_ref"),
                "store_ref": store_ref,
                "scope_grant_authority_sha256": entity_scope.get("authority_sha256"),
            },
            "products": [],
            "counts": {
                "included_products": 0,
                "approved_passport_sets": 0,
                "content_draft_ready": 0,
                "media_qa_ready": 0,
                "listing_approval_plan_ready": 0,
            },
            "excluded": {
                "count": 0,
                "by_reason": {},
                "details_disclosed": False,
            },
            "source_gaps": [f"product_content_{reason}"],
            "blockers": [
                {
                    "reason": reason,
                    "severity": "P0",
                    "owner": "identity-governance",
                    "sla_hours": 4,
                    "next_action": (
                        "establish an audited entity/store scope grant"
                        if reason == "entity_scope_authority_missing"
                        else "configure scoped Product/content authority"
                    ),
                    "workspace_href": "/commerce-os",
                }
            ],
            "control_envelope": {
                "read_only": True,
                "raw_product_content_read": False,
                "content_draft_allowed": False,
                "listing_draft_allowed": False,
                "approval_created": False,
                "permit_created": False,
                "external_write_allowed": False,
            },
        }
        payload["snapshot_sha256"] = _hash(payload)
        return payload

    @staticmethod
    def _unscoped_media() -> dict[str, Any]:
        return {
            "snapshot_sha256": None,
            "status": "no_data",
            "summary": {
                "asset_count": 0,
                "execution_count": 0,
                "failed_count": 0,
                "blocked_count": 0,
                "manifest_count": 0,
            },
            "templates": [],
            "control_envelope": {
                "listing_requires_all_qa_passed": True,
                "external_marketplace_write_allowed": False,
            },
            "source_gaps": ["scoped_media_authority_missing"],
        }

    def _stages(
        self,
        *,
        batch: dict[str, Any],
        erp: dict[str, Any],
        analytics: dict[str, Any],
        truth: dict[str, Any],
        media: dict[str, Any],
    ) -> list[dict[str, Any]]:
        counts = batch.get("counts", {})
        erp_counts = erp.get("counts", {})
        pipeline = {
            item.get("id"): int(item.get("value", 0)) for item in analytics.get("pipeline", []) if item.get("id")
        }
        views = truth.get("contribution_views", {})
        procurement_ready = sum(
            item.get("sale_triggered_procurement", {}).get("state") == "eligible_for_procurement_review"
            for item in batch.get("candidates", [])
        )
        values = {
            "observe": _count(counts, "observed_listings", "observed"),
            "identity": _count(counts, "exact_identity_matched", "exact_matched"),
            "qualify": min(
                _count(counts, "fully_costed_candidates"),
                _count(counts, "downside_positive"),
            ),
            "item_draft": _count(erp_counts, "succeeded"),
            # A global media manifest or a generic execution plan is not proof
            # that this store's exact candidate passed content or Listing
            # approval. Only candidate-scoped authority may advance the stage.
            "content": _count(counts, "content_ready"),
            "listing_approval": _count(
                counts,
                "listing_approved",
                "independently_approved_listings",
            ),
            "publish": _count(counts, "published"),
            "order": _count(counts, "ordered"),
            "procurement_review": procurement_ready,
            "fulfill": _count(counts, "fulfilled", "shipped"),
            "settle": max(
                _count(counts, "settled_proven"),
                int(self._view_ready(views.get("settlement_contribution", {}))),
            ),
            "reconcile": int(self._view_ready(views.get("cash_contribution", {}))),
            "learn": pipeline.get("observation", 0) if _count(counts, "settled_proven") > 0 else 0,
        }
        prerequisite_complete = True
        stages: list[dict[str, Any]] = []
        for (
            stage_id,
            label,
            agent_id,
            owner,
            sla_hours,
            workspace_href,
            next_action,
        ) in self.STAGES:
            value = values[stage_id]
            if value > 0:
                status = "completed"
                why = f"服务端权威快照已有 {value} 条满足该阶段的记录"
            elif stage_id == "observe":
                status = "no_data"
                why = "尚无带 Evidence 的市场观察"
            elif prerequisite_complete:
                status = "ready_for_internal_action"
                why = "前置阶段已完成，但本阶段尚无满足合同的记录"
            else:
                status = "blocked"
                why = "前置阶段尚未完成，不能跳级"
            stage = {
                "id": stage_id,
                "label": label,
                "sequence": len(stages) + 1,
                "status": status,
                "qualified_record_count": value,
                "why": why,
                "agent_id": agent_id,
                "owner": owner,
                "sla_hours": sla_hours,
                "next_action": next_action,
                "workspace_href": workspace_href,
                "evidence_required": True,
                "client_recalculation_allowed": False,
                "external_write_allowed": False,
            }
            stages.append(stage)
            prerequisite_complete = prerequisite_complete and status == "completed"
        return stages

    @staticmethod
    def _unbound_native_parity(
        *,
        principal: Principal,
        entity_scope: dict[str, Any],
        store_ref: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        basis = {
            "contract_id": "native-parity-acceptance-workspace.v1",
            "scope": {
                "tenant_ref": principal.tenant_ref,
                "entity_ref": entity_scope.get("entity_ref"),
                "store_ref": store_ref,
                "authority_sha256": entity_scope.get("authority_sha256"),
            },
            "as_of": as_of.isoformat(),
            "status": "no_data",
            "counts": {"items": 0},
            "provider_counts": {},
            "capability_counts": {},
            "items": [],
            "next_cursor": None,
            "source_gaps": ["native_parity_acceptance_not_bound"],
            "control_envelope": {
                "read_only": True,
                "client_can_recalculate_or_promote": False,
                "self_certification_allowed": False,
                "external_write_allowed": False,
            },
        }
        basis["snapshot_sha256"] = _hash(basis)
        return basis

    def _capabilities(
        self,
        stages: list[dict[str, Any]],
        native_parity: dict[str, Any],
    ) -> list[dict[str, Any]]:
        by_id = {item["id"]: item for item in stages}
        acceptance_by_capability: dict[str, list[dict[str, Any]]] = {}
        for item in native_parity.get("items", []):
            capability_id = item.get("scope", {}).get("capability_id")
            if isinstance(capability_id, str):
                acceptance_by_capability.setdefault(capability_id, []).append(item)
        expected_providers_by_capability: dict[str, set[str]] = {}
        for provider_id, capability_ids in self.BENCHMARK_CAPABILITIES.items():
            for capability_id in capability_ids:
                expected_providers_by_capability.setdefault(capability_id, set()).add(provider_id)
        capabilities = []
        for capability_id, label, stage_ids in self.CAPABILITIES:
            selected = [by_id[item] for item in stage_ids]
            if all(item["status"] == "completed" for item in selected):
                operating_status = "verified"
            elif any(item["status"] in {"completed", "ready_for_internal_action"} for item in selected):
                operating_status = "partial"
            elif all(item["status"] == "no_data" for item in selected):
                operating_status = "no_data"
            else:
                operating_status = "blocked"
            acceptance_rows = acceptance_by_capability.get(capability_id, [])
            acceptance_states = {item.get("state") for item in acceptance_rows}
            expected_providers = expected_providers_by_capability.get(capability_id, set())
            verified_providers = {
                item.get("scope", {}).get("provider_id")
                for item in acceptance_rows
                if item.get("state") == "verified_native"
            }
            verified_native = bool(expected_providers) and verified_providers == expected_providers
            if verified_native:
                implementation_status = "verified_native"
                acceptance_status = "verified_native"
            elif "blocked" in acceptance_states:
                implementation_status = "implemented_unverified"
                acceptance_status = "blocked"
            elif "stale" in acceptance_states:
                implementation_status = "implemented_unverified"
                acceptance_status = "stale"
            elif acceptance_states:
                implementation_status = "implemented_unverified"
                acceptance_status = "gated"
            else:
                implementation_status = "implemented_unverified"
                acceptance_status = "not_proven"
            capabilities.append(
                {
                    "id": capability_id,
                    "label": label,
                    "implementation_status": implementation_status,
                    "operating_status": operating_status,
                    # Shared operating-stage completion is not a
                    # capability-granular native-parity acceptance.
                    "acceptance_status": acceptance_status,
                    "verified_native": verified_native,
                    "acceptance_provider_count": len(acceptance_rows),
                    "expected_acceptance_provider_count": len(expected_providers),
                    "stage_ids": list(stage_ids),
                    "blockers": [item["why"] for item in selected if item["status"] != "completed"],
                    "truth_owner": "KJDS",
                    "third_party_fact_owner": False,
                }
            )
        return capabilities

    def _benchmarks(
        self,
        capabilities: list[dict[str, Any]],
        native_parity: dict[str, Any],
    ) -> list[dict[str, Any]]:
        registry = self._registry()
        maozierp_workflows = self._maozierp_workflow_registry()
        providers = {item["id"]: item for item in registry["providers"]}
        rows = []
        for provider_id in (
            "seerfar",
            "selling51_erp",
            "miaoshou_erp",
            "mango_erp",
            "dianxiaomi_erp",
            "maozierp",
            "lizhi_ozon_assistant",
            "linkfox",
        ):
            provider = providers[provider_id]
            targets = sorted(self.BENCHMARK_CAPABILITIES[provider_id])
            verified = sorted(
                {
                    item.get("scope", {}).get("capability_id")
                    for item in native_parity.get("items", [])
                    if item.get("scope", {}).get("provider_id") == provider_id
                    and item.get("state") == "verified_native"
                    and item.get("scope", {}).get("capability_id") in targets
                }
            )
            rows.append(
                {
                    "benchmark_id": provider_id,
                    "display_name": provider.get("display_name", provider_id),
                    "evidence_tier": provider["evidence_tier"],
                    "observed_capabilities": provider["observed_capabilities"],
                    "benchmark_capability_ids": targets,
                    "native_verified_capability_ids": verified,
                    "native_verified_count": len(verified),
                    "benchmark_capability_count": len(targets),
                    "native_gap_capability_ids": sorted(set(targets) - set(verified)),
                    "coverage_status": ("verified_parity" if len(verified) == len(targets) else "gaps_remain"),
                    "baseline_requirement": "must_have_native_parity",
                    "safe_capability_omission_allowed": False,
                    "mapping_is_not_implementation": True,
                    "benchmark_source_status": provider["integration_status"],
                    "comparison_only": True,
                    "runtime_dependency": False,
                    "integration_required": False,
                    "workflow_mapping": (maozierp_workflows if provider_id == "maozierp" else None),
                    "why": ("该产品只用于比较经营流程；完成条件是 KJDS 原生模块通过真实业务验收，不是连接该产品"),
                }
            )
        return rows

    @staticmethod
    def _native_architecture(
        capabilities: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        status = {item["id"]: item["acceptance_status"] for item in capabilities}
        definitions = (
            (
                "market_intelligence",
                "市场情报与机会",
                ("market_intelligence",),
                ("MarketplaceObservation", "BatchOpportunity"),
            ),
            (
                "pim",
                "商品与变体 PIM",
                ("exact_product_identity", "product_catalog"),
                ("CanonicalProduct", "Passport", "MarketplaceCatalog"),
            ),
            (
                "sourcing",
                "供应商与采购准备",
                ("supplier_sourcing", "procurement"),
                ("SupplierRFQ", "Sourcing", "SaleTriggeredProcurement"),
            ),
            (
                "profit_pricing",
                "利润、价格与现金",
                ("profit_and_pricing", "finance_and_settlement"),
                ("ProfitLedger", "Finance", "OzonGlobalRules"),
            ),
            (
                "content_listing",
                "内容媒体与 Listing",
                ("content_and_media", "listing_management"),
                ("ContentAsset", "MediaWorkbench", "ListingExecution"),
            ),
            (
                "oms_crm",
                "订单、退货与客服 OMS",
                ("orders_and_returns", "customer_service"),
                ("FactRecord", "Order", "OperatingTask"),
            ),
            (
                "inventory_wms",
                "库存、仓库与履约",
                ("inventory", "logistics"),
                ("InventoryFact", "LogisticsQuote", "Readback"),
            ),
            (
                "growth",
                "广告促销与实验",
                ("ads_and_promotions",),
                ("GrowthSnapshot", "CausalExperiment", "PolicyShadow"),
            ),
            (
                "organization",
                "多店、团队与主体治理",
                ("store_management", "team_governance"),
                ("Principal", "ScopeGrant", "Approval", "Audit"),
            ),
            (
                "agent_operations",
                "Agent Team 与异常运营",
                ("ai_agent_team", "operations_tasks"),
                ("OperatingWorkbench", "OperationsQueue", "EvidenceOps"),
            ),
        )
        result = []
        for module_id, label, capability_ids, authorities in definitions:
            verified = [item for item in capability_ids if status.get(item) == "verified_native"]
            module_states = {status.get(item) for item in capability_ids}
            if len(verified) == len(capability_ids):
                implementation_status = "verified_native"
                acceptance_status = "verified_native"
            elif "blocked" in module_states:
                implementation_status = "implemented_unverified"
                acceptance_status = "blocked"
            elif "stale" in module_states:
                implementation_status = "implemented_unverified"
                acceptance_status = "stale"
            elif "gated" in module_states:
                implementation_status = "implemented_unverified"
                acceptance_status = "gated"
            else:
                implementation_status = "implemented_unverified"
                acceptance_status = "not_proven"
            result.append(
                {
                    "module_id": module_id,
                    "label": label,
                    "capability_ids": list(capability_ids),
                    "authority_modules": list(authorities),
                    "implementation_status": implementation_status,
                    "acceptance_status": acceptance_status,
                    "verified_capability_count": len(verified),
                    "capability_count": len(capability_ids),
                    "native_kjds_owner": True,
                    "third_party_erp_dependency": False,
                }
            )
        return result

    def _agents(
        self,
        *,
        stages: list[dict[str, Any]],
        workbench: dict[str, Any],
        source_hashes: dict[str, str | None],
    ) -> list[dict[str, Any]]:
        by_id = {item["id"]: item for item in stages}
        queue_items = workbench.get("work_items", [])
        rows = []
        for agent_id, name, stage_ids, artifact, allowed_auto in self.AGENTS:
            selected = [by_id[item] for item in stage_ids]
            current = next(
                (item for item in selected if item["status"] != "completed"),
                selected[-1],
            )
            related = [item for item in queue_items if item.get("agent_id") == agent_id]
            rows.append(
                {
                    "agent_id": agent_id,
                    "name": name,
                    "status": (
                        "waiting_for_evidence"
                        if current["status"] in {"blocked", "no_data"}
                        else "ready_for_internal_work"
                        if current["status"] == "ready_for_internal_action"
                        else "monitoring"
                    ),
                    "stage_ids": list(stage_ids),
                    "current_focus": current["label"],
                    "why": current["why"],
                    "owner": current["owner"],
                    "sla_hours": current["sla_hours"],
                    "next_action": current["next_action"],
                    "workspace_href": current["workspace_href"],
                    "input_snapshot_hashes": source_hashes,
                    "output_artifact": artifact,
                    "allowed_automatic_actions": list(allowed_auto),
                    "queued_work_item_count": len(related),
                    "human_review_required": True,
                    "can_approve_own_output": False,
                    "can_issue_permit": False,
                    "external_write_allowed": False,
                    "model_output_is_business_fact": False,
                }
            )
        return rows

    def _registry(self) -> dict[str, Any]:
        raw = self.registry_path.read_bytes()
        payload = json.loads(raw)
        baseline = payload.get("baseline_policy", {})
        if baseline.get("requirement") != "must_have_native_parity":
            raise ValueError("Competitive baseline must require native parity")
        if baseline.get("safe_capability_omission_allowed") is not False:
            raise ValueError("Competitive baseline cannot omit safe capability")
        if baseline.get("mapping_is_not_implementation") is not True:
            raise ValueError("Competitive mapping cannot claim implementation")
        if baseline.get("providers_are_runtime_dependencies") is not False:
            raise ValueError("Benchmark providers cannot be runtime dependencies")
        if baseline.get("external_write_allowed") is not False:
            raise ValueError("Benchmark registry cannot enable external writes")
        providers = [item for item in payload["providers"] if item["id"] in self.BENCHMARK_CAPABILITIES]
        provider_ids = {item["id"] for item in providers}
        missing = set(self.BENCHMARK_CAPABILITIES) - provider_ids
        if missing:
            raise ValueError("Competitive baseline providers missing: " + ", ".join(sorted(missing)))
        return {
            "registry_version": payload["registry_version"],
            "baseline_policy": baseline,
            "providers": providers,
            "snapshot_sha256": hashlib.sha256(raw).hexdigest(),
        }

    def _maozierp_workflow_registry(self) -> dict[str, Any]:
        raw = self.maozierp_benchmark_path.read_bytes()
        payload = json.loads(raw)
        capabilities = payload.get("capabilities", [])
        coverage = payload.get("coverage", {})
        if payload.get("contract_id") != ("kjds-competitive-capability-benchmark-v1"):
            raise ValueError("Unsupported Maozi capability benchmark contract")
        capability_ids = [item.get("id") for item in capabilities]
        if (
            not capabilities
            or any(not item for item in capability_ids)
            or len(set(capability_ids)) != len(capability_ids)
        ):
            raise ValueError("Maozi capability benchmark IDs must be unique")
        mapped_count = len(
            [
                item
                for item in capabilities
                if item.get("kjds_target")
                and item.get("adoption")
                and item.get("wave")
                and item.get("status")
                and item.get("boundary")
            ]
        )
        if coverage.get("observed_capability_count") != len(capabilities):
            raise ValueError("Maozi observed capability count drift")
        if coverage.get("mapped_count") != mapped_count:
            raise ValueError("Maozi mapped capability count drift")
        if coverage.get("unmapped_count") != len(capabilities) - mapped_count:
            raise ValueError("Maozi unmapped capability count drift")
        if coverage.get("external_write_allowed") is not False:
            raise ValueError("Maozi benchmark cannot enable external writes")
        if coverage.get("implementation_is_not_claimed_by_mapping") is not True:
            raise ValueError("Maozi benchmark must keep mapping and implementation separate")
        adoption_summary: dict[str, int] = {}
        status_summary: dict[str, int] = {}
        for item in capabilities:
            adoption = str(item["adoption"])
            status = str(item["status"])
            adoption_summary[adoption] = adoption_summary.get(adoption, 0) + 1
            status_summary[status] = status_summary.get(status, 0) + 1
        if adoption_summary != coverage.get("adoption_summary"):
            raise ValueError("Maozi adoption summary drift")
        source = payload["source"]
        return {
            "contract_id": payload["contract_id"],
            "benchmark_id": payload["benchmark_id"],
            "mapping_status": "mapped_not_implemented",
            "source": {
                "title": source["title"],
                "url": source["url"],
                "observed_at": source["observed_at"],
                "evidence_tier": source["evidence_tier"],
                "authority": source["authority"],
                "capability_snapshot_sha256": source["capability_snapshot_sha256"],
            },
            "observed_capability_count": len(capabilities),
            "mapped_count": mapped_count,
            "unmapped_count": len(capabilities) - mapped_count,
            "adoption_summary": adoption_summary,
            "implementation_status_summary": status_summary,
            "implementation_is_not_claimed": True,
            "external_write_allowed": False,
            "capabilities": [
                {
                    "id": item["id"],
                    "observed": item["observed"],
                    "kjds_target": item["kjds_target"],
                    "adoption": item["adoption"],
                    "wave": item["wave"],
                    "implementation_status": item["status"],
                    "boundary": item["boundary"],
                }
                for item in capabilities
            ],
            "snapshot_sha256": hashlib.sha256(raw).hexdigest(),
        }

    @staticmethod
    def _batch_evidence_ids(batch: dict[str, Any]) -> list[str]:
        values = [batch.get("evidence_id")]
        for candidate in batch.get("candidates", []):
            values.extend(
                [
                    candidate.get("candidate_evidence_id"),
                    *candidate.get("evidence_ids", []),
                ]
            )
        return sorted({str(item).strip() for item in values if item is not None and str(item).strip()})[:500]

    @staticmethod
    def _view_ready(view: Any) -> bool:
        if not isinstance(view, dict):
            return False
        return view.get("status") in {
            "ready",
            "available",
            "reconciled",
            "verified",
        }

    @staticmethod
    def _as_of(value: str | None) -> datetime:
        if value is None:
            return datetime.now(UTC)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("as_of must include timezone")
        parsed = parsed.astimezone(UTC)
        if parsed > datetime.now(UTC):
            raise ValueError("as_of cannot be in the future")
        return parsed

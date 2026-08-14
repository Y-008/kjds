from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = (
    ROOT
    / "docs"
    / "project"
    / "registries"
    / "cross_border_capability_atlas.json"
)

STATUS = {"implemented", "ready", "gated", "research_only"}
REGISTRY_VERSION = "0.59.0"
DOMAIN_WORKSPACE_IDS = {
    "overview",
    "data",
    "research",
    "products",
    "pilot",
    "sourcing",
    "growth",
    "finance",
    "science",
    "governance",
    "system",
    "evidenceops",
}
FALLBACK_WORKSPACE_BY_DOMAIN = {
    "command_and_assets": "research",
    "governance_and_global": "system",
}
SOURCE_KINDS = {
    "linkfox_public_C": {
        "evidence_tier": "C",
        "boundary": "公开页面可见工作流；不证明 API、模型效果、平台接入或经营结果。",
    },
    "repository_verified": {
        "evidence_tier": "repository_contract",
        "boundary": "代码、测试或版本化合同已存在；不自动证明外部业务结果。",
    },
    "product_architecture": {
        "evidence_tier": "design",
        "boundary": "产品与技术合同已设计；只有通过真实样本和门禁后才能晋级。",
    },
}

PROFILES: dict[str, dict[str, Any]] = {
    "research_ingest": {
        "operation_kind": "query",
        "input_contract": ["来源定位", "观察时间", "许可/用途范围"],
        "output_contract": ["不可变来源快照", "结构化候选信号", "来源置信度"],
        "technology": "来源适配器 + 确定性解析 + PostgreSQL 全文检索 + schema replay",
        "evidence_gate": "保留原始 Evidence；C 级信号不得晋升账户或平台事实。",
        "failure_modes": ["来源不可达", "许可未知", "schema 漂移", "重复信号"],
        "failure_queue": "research_signal_review",
        "readback": "以来源哈希、解析版本和复核结论重放。",
        "kpi": ["可追溯率", "重复率", "人工采纳率", "信号新鲜度"],
        "sla": "24h 内完成新鲜度和许可复核",
        "controls": ["read_only", "provenance_required", "no_fact_promotion"],
    },
    "deterministic_transform": {
        "operation_kind": "transform",
        "input_contract": ["版本化业务对象", "转换 profile", "幂等键"],
        "output_contract": ["确定性产物", "差异报告", "lineage edge"],
        "technology": "版本化 JSON Schema + 确定性转换 DAG + 内容哈希",
        "evidence_gate": "输入对象、规则版本和输出哈希必须可重放。",
        "failure_modes": ["字段缺失", "规则冲突", "单位/币种错误", "幂等冲突"],
        "failure_queue": "contract_transform_review",
        "readback": "用相同输入和规则重算并比对哈希。",
        "kpi": ["确定性通过率", "schema 合格率", "重放一致率"],
        "sla": "同步校验；失败立即关闭",
        "controls": ["schema_validated", "idempotent", "lineage_required"],
    },
    "generative_candidate": {
        "operation_kind": "recommendation",
        "input_contract": ["已授权 Evidence", "结构化 brief", "模型/Skill 版本"],
        "output_contract": ["候选内容", "事实引用", "QA/不确定性报告"],
        "technology": "provider-neutral adapter + structured output + retrieval grounding + eval harness",
        "evidence_gate": "生成结果只能是候选；事实字段必须引用 Passport/Evidence。",
        "failure_modes": ["幻觉", "敏感表达", "语言不自然", "事实漂移", "成本超限"],
        "failure_queue": "content_candidate_review",
        "readback": "记录提示摘要、模型、输入哈希、成本、延迟和人工结论。",
        "kpi": ["一次验收率", "事实一致率", "俄语母语通过率", "单产物成本"],
        "sla": "进入交付前完成人工与规则 QA",
        "controls": ["candidate_only", "human_approval", "model_eval_required"],
    },
    "visual_generation": {
        "operation_kind": "recommendation",
        "input_contract": ["有权源图/视频", "Product Passport", "品牌/平台 profile"],
        "output_contract": ["视觉候选", "逐资产 QA", "生成 lineage"],
        "technology": "multimodal provider router + perceptual diff + OCR/attribute QA + deterministic manifest",
        "evidence_gate": "权利、商品保真、文字、平台规格和人工批准同时通过。",
        "failure_modes": ["商品结构漂移", "颜色漂移", "文字错误", "权利未知", "比例不合规"],
        "failure_queue": "visual_fidelity_review",
        "readback": "原图/结果/模型/参数/QA/批准记录形成可重放 manifest。",
        "kpi": ["商品保真率", "OCR 通过率", "平台 QA 通过率", "人工返工率"],
        "sla": "批次交付前完成逐资产 QA",
        "controls": ["rights_review", "product_fidelity", "human_approval"],
    },
    "content_delivery": {
        "operation_kind": "command",
        "input_contract": ["已批准内容候选", "平台 profile", "用途/期限"],
        "output_contract": ["不可变交付 manifest", "下载/分发包", "QA 收据"],
        "technology": "content-addressed assets + SHA-256 manifest + policy-as-data",
        "evidence_gate": "只有已核权、已 QA、已批准资产可进入交付包。",
        "failure_modes": ["资产缺失", "manifest 不一致", "许可过期", "平台规格不符"],
        "failure_queue": "delivery_manifest_review",
        "readback": "按 manifest 哈希校验每个派生资产和用途。",
        "kpi": ["交付完整率", "下载可用率", "许可过期拦截率"],
        "sla": "交付前同步失败关闭",
        "controls": ["immutable_manifest", "rights_scope", "approval_required"],
    },
    "platform_read": {
        "operation_kind": "query",
        "input_contract": ["专用只读身份", "版本化 endpoint contract", "范围/游标"],
        "output_contract": ["原始响应 Evidence", "规范化对象", "schema 差异"],
        "technology": "isolated provider adapter + bounded retry/circuit breaker + fixture replay",
        "evidence_gate": "只接受已固定合同与真实脱敏样本；schema 漂移失败关闭。",
        "failure_modes": ["鉴权失败", "限流", "超时", "schema 漂移", "范围越权"],
        "failure_queue": "platform_read_exception",
        "readback": "原始响应哈希与规范化对象双向比对。",
        "kpi": ["成功率", "P95 延迟", "漂移拦截率", "Evidence 完整率"],
        "sla": "有界重试后进入人工队列",
        "controls": ["read_only_identity", "scope_guard", "schema_drift_fail_closed"],
    },
    "controlled_write": {
        "operation_kind": "command",
        "input_contract": ["已批准对象", "Execution Permit", "幂等键"],
        "output_contract": ["写入回执", "平台 readback", "补偿/回滚引用"],
        "technology": "least-privilege worker + outbox/lease + idempotency + readback verifier",
        "evidence_gate": "批准、Permit、作用域、预算、Kill Switch 和回读合同全部有效。",
        "failure_modes": ["Permit 过期", "平台拒绝", "部分成功", "回读不一致", "预算超限"],
        "failure_queue": "controlled_execution_exception",
        "readback": "写入回执必须由独立读取复验，不以 HTTP 200 作为完成。",
        "kpi": ["批准写入成功率", "回读一致率", "越权拦截数", "补偿成功率"],
        "sla": "回读不一致立即冻结同作用域后续写入",
        "controls": ["permit_required", "kill_switch", "independent_readback", "rollback"],
    },
    "human_review": {
        "operation_kind": "decision",
        "input_contract": ["待审对象", "Evidence 包", "规则/差异"],
        "output_contract": ["实名决定", "理由", "有效期/作用域"],
        "technology": "separation-of-duties policy + append-only decision record",
        "evidence_gate": "复核人不得与提交人相同；缺原件或差异未解决不得批准。",
        "failure_modes": ["职责冲突", "证据缺失", "超期", "理由不足"],
        "failure_queue": "human_attention_queue",
        "readback": "决定引用的 Evidence 和对象哈希必须仍然匹配。",
        "kpi": ["队列年龄", "一次通过率", "职责分离违规数"],
        "sla": "按风险等级 4h/24h/72h",
        "controls": ["named_owner", "separation_of_duties", "expiry_required"],
    },
    "financial_projection": {
        "operation_kind": "projection",
        "input_contract": ["权威/估算来源", "Decimal 金额", "币种/税务/时间语义"],
        "output_contract": ["版本化计算快照", "来源等级", "差异/敏感性"],
        "technology": "Decimal canonical calculator + authoritative FX + immutable snapshot",
        "evidence_gate": "estimate、actual、reconciled 分层；不得用估算覆盖权威账。",
        "failure_modes": ["币种缺失", "FX 过期", "费用漏项", "结算差异", "舍入冲突"],
        "failure_queue": "finance_reconciliation_exception",
        "readback": "逐费用项回溯原始 Evidence 并重算 Decimal 快照。",
        "kpi": ["CM3 完整率", "预测/实际偏差", "未对账金额", "队列年龄"],
        "sla": "关键金额差异 T+1 进入复核",
        "controls": ["decimal_only", "authority_tier", "no_estimate_promotion"],
    },
    "governance_control": {
        "operation_kind": "control",
        "input_contract": ["受控对象/轨迹", "策略版本", "责任范围"],
        "output_contract": ["允许/阻断决定", "审计记录", "补救动作"],
        "technology": "policy-as-data + deterministic guard + append-only audit",
        "evidence_gate": "控制结论必须引用策略版本、对象哈希和责任身份。",
        "failure_modes": ["策略缺失", "范围不明", "身份越权", "审计不完整"],
        "failure_queue": "governance_exception",
        "readback": "用同一策略版本对对象/轨迹重放控制结论。",
        "kpi": ["越权拦截数", "审计完整率", "例外关闭时间"],
        "sla": "高风险违规立即阻断",
        "controls": ["fail_closed", "least_privilege", "audit_required"],
    },
    "batch_runtime": {
        "operation_kind": "orchestration",
        "input_contract": ["批次 manifest", "配额/并发预算", "可重试任务"],
        "output_contract": ["逐项结果", "批次账本", "失败/重试队列"],
        "technology": "PostgreSQL lease/outbox + bounded concurrency + resumable task ledger",
        "evidence_gate": "批次不得绕过单项 Evidence、QA、审批或写权限门。",
        "failure_modes": ["配额耗尽", "部分失败", "租约超时", "毒任务", "重复执行"],
        "failure_queue": "batch_runtime_exception",
        "readback": "按逐项幂等键和产物哈希复核，不用批次成功掩盖单项失败。",
        "kpi": ["吞吐量", "部分失败率", "重试恢复率", "单位成本"],
        "sla": "失败可暂停、恢复并人工接管",
        "controls": ["bounded_concurrency", "per_item_gate", "resumable", "budget_enforced"],
    },
}


def build_graph(atlas: dict[str, Any]) -> dict[str, Any]:
    capability_index: dict[str, tuple[str, dict[str, Any]]] = {}
    for domain in atlas["domains"]:
        for capability in domain["capabilities"]:
            capability_index[capability["id"]] = (domain["id"], capability)

    points: list[dict[str, Any]] = []

    def add(
        point_id: str,
        label: str,
        parent: str,
        profile_id: str,
        business_object: str,
        status: str,
        source_kind: str,
        streams: list[str],
        objective: str,
        *,
        platforms: list[str] | None = None,
        markets: list[str] | None = None,
        owner: str | None = None,
        reviewer: str = "经营复核 / 风险与合规",
    ) -> None:
        if status not in STATUS:
            raise ValueError(f"Unknown status for {point_id}: {status}")
        domain_id, capability = capability_index[parent]
        profile = PROFILES[profile_id]
        source = SOURCE_KINDS[source_kind]
        legacy_workspace = capability["workspace"]
        workspace_id = (
            legacy_workspace.removeprefix("/#")
            if legacy_workspace.startswith("/#")
            else "evidenceops"
            if legacy_workspace == "/evidenceops"
            else FALLBACK_WORKSPACE_BY_DOMAIN.get(domain_id, "overview")
        )
        if workspace_id not in DOMAIN_WORKSPACE_IDS:
            raise ValueError(
                f"Unknown domain workspace for {point_id}: {workspace_id}"
            )
        points.append(
            {
                "id": point_id,
                "label": label,
                "domain_id": domain_id,
                "parent_capability_id": parent,
                "objective": objective,
                "business_object": business_object,
                "operation_kind": profile["operation_kind"],
                "contract_profile_id": profile_id,
                "source_kind": source_kind,
                "evidence_tier": source["evidence_tier"],
                "source_boundary": source["boundary"],
                "status": status,
                "input_contract": list(profile["input_contract"]),
                "output_contract": list(profile["output_contract"]),
                "technology": profile["technology"],
                "evidence_gate": profile["evidence_gate"],
                "failure_modes": list(profile["failure_modes"]),
                "failure_queue": profile["failure_queue"],
                "readback": profile["readback"],
                "kpi": list(profile["kpi"]),
                "sla": profile["sla"],
                "owner": owner or "Domain Operator",
                "reviewer": reviewer,
                "markets": markets or list(capability["markets"]),
                "platforms": platforms or list(capability["platforms"]),
                "controls": sorted(set(profile["controls"] + capability["controls"])),
                "value_stream_ids": streams,
                "workspace_id": workspace_id,
                "workspace": f"/operations/points/{point_id}",
            }
        )

    # 01 · Command, product truth and reusable assets.
    add("trend_event_calendar", "站点节日与趋势日历", "inspiration_library", "research_ingest", "TrendEvent", "ready", "linkfox_public_C", ["trend_to_opportunity"], "按国家、平台、类目和时间窗组织可追溯活动机会。")
    add("inspiration_signal_capture", "灵感信号收件箱", "inspiration_library", "research_ingest", "ResearchSignal", "implemented", "repository_verified", ["trend_to_opportunity", "signal_to_experiment"], "把公开线索与内部观察隔离为待复核信号。")
    add("public_source_snapshot", "公开来源不可变快照", "link_management", "research_ingest", "RawEvidence", "implemented", "repository_verified", ["trend_to_opportunity", "signal_to_experiment"], "冻结 URL、时间、原始内容、许可和解析版本。")
    add("reference_url_parse", "参考 URL 解析", "link_management", "research_ingest", "ReferenceListingCandidate", "ready", "linkfox_public_C", ["trend_to_opportunity"], "解析参考商品但不把公开页面提升为账户事实。")
    add("catalog_csv_import", "CSV/XLSX 目录导入", "link_management", "deterministic_transform", "CatalogImportBatch", "implemented", "repository_verified", ["product_to_passport"], "带字段映射、逐行错误和幂等语义导入目录候选。")
    add("reference_link_workspace", "自有/参考链接工作区", "link_management", "deterministic_transform", "ListingReference", "ready", "linkfox_public_C", ["trend_to_opportunity", "product_to_passport"], "区分自有链接、公开参考、来源级别和可用范围。")
    add("canonical_product_identity", "Canonical Product 身份", "product_management", "deterministic_transform", "CanonicalProduct", "implemented", "repository_verified", ["product_to_passport"], "建立不依赖任何单一平台或 ERP 的稳定商品身份。")
    add("external_listing_identity_map", "平台 Listing 身份映射", "product_management", "deterministic_transform", "ExternalIdentityMap", "implemented", "repository_verified", ["product_to_passport", "listing_to_publish"], "把 Ozon offer/SKU 与内部 Product 稳定映射并保留历史。", platforms=["ozon"], markets=["RU"])
    add("product_passport_assembly", "商品三类 Passport 组装", "product_management", "deterministic_transform", "ProductPassport", "implemented", "repository_verified", ["product_to_passport", "passport_to_content"], "从目录、人工确认、供应商和合规原件组装可引用商品真源。")
    add("media_delivery_manifest", "图片交付 Manifest", "image_delivery", "content_delivery", "ContentDeliveryManifest", "implemented", "repository_verified", ["passport_to_content", "content_to_listing"], "逐资产绑定哈希、来源、QA、批准、用途和期限。")
    add("asset_rights_scope", "素材权利与地域作用域", "asset_library", "governance_control", "AssetRightsGrant", "ready", "product_architecture", ["product_to_passport", "passport_to_content"], "控制资产在市场、平台、店铺和期限内的派生与撤销。")
    add("brand_token_registry", "品牌基因 Token 注册表", "brand_compliance", "deterministic_transform", "BrandProfile", "implemented", "repository_verified", ["product_to_passport", "passport_to_content"], "版本化颜色、字体、语气、商标和替换词。")
    add("sensitive_term_rulepack", "敏感词与合规规则包", "brand_compliance", "governance_control", "ComplianceRulePack", "implemented", "repository_verified", ["product_to_passport", "content_to_listing"], "以官方规则优先顺序校验俄语和平台表达。")
    add("team_asset_workspace", "个人/项目/团队素材空间", "asset_library", "governance_control", "AssetWorkspace", "ready", "linkfox_public_C", ["passport_to_content"], "按 tenant/store/market 隔离素材、模板和撤销传播。")

    # 02 · Agent, conversation, plugin and scheduled work.
    add("ai_free_conversation", "AI 自由会话", "ai_conversation", "generative_candidate", "ConversationCandidate", "ready", "linkfox_public_C", ["trend_to_opportunity", "passport_to_content"], "在 Evidence 边界内回答经营与内容问题，不直接执行外部写入。")
    add("observed_zx35_conversation", "ZX-3.5 会话入口（公开观察）", "ai_conversation", "generative_candidate", "ObservedModelEntry", "research_only", "linkfox_public_C", ["passport_to_content"], "保留公开套餐功能名，不把型号、能力或可用性作为 KJDS 事实。")
    add("observed_zx4_conversation", "ZX-4 会话入口（公开观察）", "ai_conversation", "generative_candidate", "ObservedModelEntry", "research_only", "linkfox_public_C", ["passport_to_content"], "保留公开套餐功能名，不把型号、能力或可用性作为 KJDS 事实。")
    add("objective_interpreter", "经营目标解释器", "ai_conversation", "generative_candidate", "OperatingObjective", "implemented", "repository_verified", ["trend_to_opportunity", "passport_to_content"], "把自然语言目标拆成事实、未知、任务、验证条件和控制包。")
    add("product_profile_agent", "商品档案 Agent", "agent_product_and_glossary", "generative_candidate", "ProductProfileCandidate", "ready", "linkfox_public_C", ["trend_to_opportunity", "product_to_passport"], "以 Passport 引用生成可审查商品画像，不覆盖商品真源。")
    add("multilingual_glossary", "多语术语与知识库", "agent_product_and_glossary", "deterministic_transform", "MarketGlossary", "ready", "linkfox_public_C", ["passport_to_content", "content_to_listing"], "锁定商品术语、禁译项、RU 母语表达和全球 locale 版本。")
    add("personal_prompt_template", "个人提示模板", "ai_conversation", "governance_control", "PromptTemplate", "ready", "linkfox_public_C", ["passport_to_content"], "保存可版本化、可评测、不可夹带密钥的个人模板。")
    add("template_conversation", "模板化 AI 会话", "ai_conversation", "generative_candidate", "StructuredConversation", "ready", "linkfox_public_C", ["passport_to_content"], "按固定输入 Schema 和输出 Schema 运行经营模板。")
    add("sensitive_word_preflight", "会话敏感词预检", "ai_conversation", "governance_control", "ContentPreflight", "ready", "linkfox_public_C", ["passport_to_content", "content_to_listing"], "在模型调用前后双向执行确定性敏感词和政策校验。")
    add("page_context_capture", "页面上下文识别插件", "skill_marketplace", "research_ingest", "PageContextEvidence", "gated", "linkfox_public_C", ["trend_to_opportunity", "signal_to_experiment"], "只在用户授权范围捕获页面上下文并清晰显示来源与时间。")
    add("operating_template_catalog", "运营模板目录", "skill_marketplace", "governance_control", "OperatingTemplate", "ready", "linkfox_public_C", ["trend_to_opportunity", "passport_to_content", "signal_to_experiment"], "把模板绑定输入合同、输出合同、评测集和允许工具。")
    add("evidence_grounded_analysis", "Evidence 驱动智能分析", "ai_conversation", "generative_candidate", "AnalysisCandidate", "implemented", "repository_verified", ["trend_to_opportunity", "signal_to_experiment"], "所有结论区分事实、推断和未知，并引用 Evidence。")
    add("skill_plan_builder", "Skill/Agent 计划构建器", "skill_marketplace", "governance_control", "AgentPlan", "implemented", "repository_verified", ["passport_to_content", "exception_to_human_control"], "分离计划、工具选择、批准、执行和回读。")
    add("scheduled_agent_task", "定时 Agent 任务", "scheduled_tasks", "batch_runtime", "ScheduledTask", "gated", "linkfox_public_C", ["signal_to_experiment", "exception_to_human_control"], "带预算、租约、暂停、恢复和人工接管运行定时任务。")
    add("claw_worker_admission", "Claw/云端 Worker 准入", "claw_cloud_worker", "governance_control", "ExternalWorkerAdmission", "gated", "linkfox_public_C", ["exception_to_human_control"], "只允许经过身份、权限、数据、评测、成本和回滚审查的外部 Worker。")

    # 03 · Product imagery.
    for spec in [
        ("product_image_suite", "商品套图", "product_image_suite", "ProductImageSet", "生成白底、场景、卖点、细节和尺寸等平台套图。"),
        ("product_replace", "商品替换", "product_replace", "ProductComposite", "在保持场景结构时替换商品并执行比例/遮挡 QA。"),
        ("scene_variation", "商品场景裂变", "product_scene_variation", "SceneVariantSet", "从一个核权场景生成多构图候选而不改变商品事实。"),
        ("handheld_composite", "手持商品图", "handheld_product", "HandheldComposite", "生成人手持商品候选并检测手部、比例、遮挡和品牌。"),
        ("image_translation", "图片文字翻译", "image_translation", "LocalizedImage", "提取文字、锁定商品词、俄语母语翻译并回填版式。"),
        ("white_background", "白底主图", "white_background_and_closeup", "WhiteBackgroundAsset", "生成符合平台背景、边距、比例和分辨率要求的主图。"),
        ("detail_closeup", "商品细节特写", "white_background_and_closeup", "DetailAsset", "生成不虚构材质和结构的细节视图。"),
        ("selling_point_card", "卖点信息图", "product_image_suite", "SellingPointAsset", "从 Passport 引用卖点并做 OCR 与敏感词校验。"),
        ("spec_size_card", "规格/尺寸图", "product_image_suite", "SpecificationAsset", "从结构化尺寸真源生成单位明确的规格图。"),
        ("batch_product_variants", "商品图批量变体", "batch_generation", "VisualBatch", "按逐 SKU 权利和 QA 门批量生成变体。"),
    ]:
        add(spec[0], spec[1], spec[2], "visual_generation" if spec[0] != "batch_product_variants" else "batch_runtime", spec[3], "ready", "linkfox_public_C", ["passport_to_content"], spec[4])

    # 04 · Apparel and model imagery.
    for spec in [
        ("apparel_image_suite", "服装套图", "apparel_image_suite", "ApparelImageSet", "生成模特、白底、UGC、卖点、尺码和细节套图。"),
        ("model_swap", "真人换模特", "model_swap", "ModelSwapAsset", "替换模特同时保持服装版型、纹理和颜色。"),
        ("model_scene_swap", "模特换场景", "model_scene_swap", "ModelSceneAsset", "保持人物与服装一致性，只替换核权场景。"),
        ("virtual_try_on", "AI 穿衣", "virtual_try_on", "VirtualTryOnAsset", "将服装映射到人物候选并标记非实拍边界。"),
        ("pose_variation", "姿势裂变", "pose_variation", "PoseVariantSet", "在服装保真和人体合理性门内生成姿势候选。"),
        ("wearable_composite", "AI 穿戴", "wearable_composite", "WearableComposite", "合成饰品/穿戴商品并检查尺度、遮挡和佩戴位置。"),
        ("apparel_ugc_card", "服装 UGC 候选", "apparel_image_suite", "ApparelUgcAsset", "生成清晰标注为合成内容的生活化服装图。"),
        ("apparel_size_card", "服装尺码图", "apparel_image_suite", "ApparelSizeAsset", "从 RU 尺码映射和供应商原件生成尺码图。"),
        ("garment_fidelity_qa", "服装保真 QA", "apparel_image_suite", "GarmentFidelityReport", "用局部特征、颜色和结构差异拦截商品漂移。"),
    ]:
        add(spec[0], spec[1], spec[2], "visual_generation", spec[3], "ready", "linkfox_public_C" if spec[0] != "garment_fidelity_qa" else "product_architecture", ["passport_to_content"], spec[4])

    # 05 · Design and POD.
    for spec in [
        ("design_canvas", "商品图设计画布", "design_workspace", "DesignDocument", "组织资产、文案、品牌组件和平台安全区。"),
        ("platform_design_template", "平台设计模板", "design_workspace", "PlatformTemplate", "按 Ozon/Amazon 等 profile 生成可复用尺寸和布局模板。"),
        ("personal_design_template", "个人设计模板", "design_workspace", "PersonalTemplate", "保存个人可版本化模板及依赖资产。"),
        ("team_design_template", "团队设计模板", "design_workspace", "TeamTemplate", "团队模板带 Owner、发布、弃用和权限。"),
        ("pod_scene_material", "POD 场景素材", "pod_materials", "PodSceneAsset", "生成/管理具备许可与商品适配信息的 POD 场景。"),
        ("similar_design_variation", "相似图裂变", "pod_materials", "PodDesignVariant", "基于有权设计生成差异候选并检测近似侵权风险。"),
        ("free_ai_drawing", "AI 自由绘图", "pod_materials", "GeneratedArtwork", "生成独立创意候选并保留模型、提示和许可记录。"),
        ("pod_material_fit", "素材贴合", "pod_materials", "PodFitPreview", "按产品曲面、可印区和出血规则生成贴合预览。"),
        ("print_extract", "印花提取", "pod_materials", "PrintExtraction", "从有权商品图提取印花并记录来源和使用范围。"),
        ("design_preflight", "设计交付预检", "design_workspace", "DesignPreflightReport", "检查分辨率、色彩、出血、字体、权利和平台规则。"),
    ]:
        add(spec[0], spec[1], spec[2], "visual_generation" if spec[0] not in {"design_canvas", "platform_design_template", "personal_design_template", "team_design_template"} else "deterministic_transform", spec[3], "ready", "linkfox_public_C", ["passport_to_content"], spec[4])

    # 06 · Image repair atomics from the public price matrix.
    for point_id, label, parent, obj, objective in [
        ("smart_repair", "智能修图/融合", "smart_repair_and_fusion", "RepairedAsset", "自动选择修复、融合、抠图或扩图步骤并逐步留痕。"),
        ("long_image_rebuild", "长图复刻", "long_image_rebuild", "LongImageCandidate", "解析长图区块并用自有商品事实重建，不复制第三方资产。"),
        ("local_inpaint", "局部重绘", "inpaint_erase", "InpaintAsset", "在显式蒙版内重绘并检测对商品主体的越界影响。"),
        ("local_erase", "局部消除", "inpaint_erase", "EraseAsset", "删除指定元素并保留蒙版和前后差异。"),
        ("recolor", "一键换色", "recolor_and_print", "RecolorAsset", "按批准色板换色并输出 ΔE/商品保真报告。"),
        ("recolor_v2", "一键换色 2.0", "recolor_and_print", "MaterialAwareRecolor", "材质感知换色，区分表面、阴影和反射区域。"),
        ("image_crop", "图片裁剪", "crop_upscale_outpaint", "CroppedAsset", "按平台安全区、焦点和比例确定性裁剪。"),
        ("image_upscale", "高清放大", "crop_upscale_outpaint", "UpscaledAsset", "放大并检测文字、纹理和边缘伪影。"),
        ("image_outpaint", "智能扩图", "crop_upscale_outpaint", "OutpaintAsset", "扩展背景但锁定商品主体边界。"),
        ("product_retouch", "商品精修", "product_retouch_cutout", "RetouchedAsset", "修复灰尘、光影和瑕疵但不虚构结构/材质。"),
        ("color_difference_repair", "色差修复", "product_retouch_cutout", "ColorCorrectedAsset", "依据核准色样修复色差并记录校准条件。"),
        ("print_repair", "印花修复", "recolor_and_print", "PrintRepairedAsset", "修复断裂/畸变印花并对照原始设计。"),
        ("hand_repair", "手部修复", "product_retouch_cutout", "HandRepairedAsset", "修复手部异常并复查商品遮挡和尺度。"),
        ("precision_cutout", "精细抠图", "product_retouch_cutout", "CutoutAsset", "生成透明通道、边缘质量和残留背景报告。"),
        ("batch_auto_cutout", "批量自动抠图", "batch_generation", "CutoutBatch", "批量抠图但逐图保留质量门与失败队列。"),
    ]:
        add(point_id, label, parent, "batch_runtime" if point_id == "batch_auto_cutout" else "visual_generation", obj, "ready", "linkfox_public_C", ["passport_to_content"], objective)

    # 07 · Video.
    for point_id, label, parent, profile, obj, objective in [
        ("image_to_video", "图转视频", "image_to_video", "visual_generation", "ProductVideoCandidate", "从批准图片生成镜头运动候选并锁定商品事实。"),
        ("talking_avatar", "带货口播", "talking_avatar", "visual_generation", "TalkingAvatarCandidate", "组合已授权形象、俄语脚本和语音并标记合成。"),
        ("localized_script_voice", "俄语脚本与语音本地化", "talking_avatar", "generative_candidate", "LocalizedVoiceScript", "术语锁定、母语审查、声明和语音许可一体化。"),
        ("video_clone", "视频复刻", "video_clone_edit", "visual_generation", "VideoStructureCandidate", "仅借鉴公开结构节奏，使用自有资产重制并检测版权边界。"),
        ("video_stitch", "视频拼接", "video_clone_edit", "deterministic_transform", "VideoTimeline", "按镜头清单、转场和时长确定性拼接。"),
        ("video_caption_trim", "剪辑/字幕/节奏", "video_clone_edit", "deterministic_transform", "CaptionedVideo", "生成时间轴、俄语字幕、安全区和平台时长版本。"),
        ("video_product_truth_qa", "视频商品真值 QA", "image_to_video", "visual_generation", "VideoTruthReport", "逐关键帧检测商品结构、数量、颜色、文字和声明漂移。"),
        ("platform_video_encode", "平台视频编码", "video_clone_edit", "deterministic_transform", "PlatformVideoAsset", "按平台 profile 输出编码、比例、码率和封装。"),
        ("video_delivery_manifest", "视频交付 Manifest", "video_clone_edit", "content_delivery", "VideoDeliveryManifest", "绑定源资产、时间轴、语音/音乐许可、QA 和批准。"),
    ]:
        add(point_id, label, parent, profile, obj, "ready", "linkfox_public_C" if point_id not in {"localized_script_voice", "video_product_truth_qa", "platform_video_encode", "video_delivery_manifest"} else "product_architecture", ["passport_to_content", "content_to_listing"], objective)

    # 08 · Enterprise throughput and API boundary.
    for point_id, label, parent, obj, status, objective in [
        ("compute_quota", "算力额度账本", "compute_and_quota", "ComputeBudget", "ready", "按租户、项目、模型和用途记录预算与消耗。"),
        ("concurrency_budget", "图片/任务并发预算", "compute_and_quota", "ConcurrencyBudget", "ready", "按优先级实行有界并发和背压。"),
        ("storage_budget", "存储配额", "compute_and_quota", "StorageBudget", "ready", "按资产类型、权利和保留策略管理存储。"),
        ("history_retention", "创作历史保留策略", "team_collaboration", "RetentionPolicy", "ready", "版本化保留、删除、导出和法律留置边界。"),
        ("priority_queue_policy", "任务优先级队列", "compute_and_quota", "QueuePolicy", "ready", "控制紧急、交付、实验和批处理任务的公平性。"),
        ("account_team_scope", "账号/团队作用域", "team_collaboration", "TeamScope", "ready", "隔离个人、团队、店铺、市场和审查角色。"),
        ("batch_ai_conversation", "AI 会话批处理", "batch_generation", "ConversationBatch", "ready", "逐项复用会话 Schema、预算和审核门。"),
        ("batch_image_generation", "AI 图片批量生成", "batch_generation", "ImageBatch", "ready", "逐 SKU 权利、保真、QA 和批准不被批次绕过。"),
        ("enterprise_api_admission", "企业 API 准入", "team_collaboration", "ApiClientAdmission", "gated", "公开套餐只观察到 API 示例；KJDS 需独立身份、契约、配额、审计和撤销。"),
    ]:
        add(point_id, label, parent, "governance_control" if point_id in {"history_retention", "account_team_scope", "enterprise_api_admission"} else "batch_runtime", obj, status, "linkfox_public_C", ["passport_to_content", "exception_to_human_control"], objective)

    # 09 · Russia/Ozon end-to-end operations, using only repository-tested contracts.
    add("market_signal_inbox", "市场信号收件箱", "market_research", "research_ingest", "MarketSignal", "implemented", "repository_verified", ["trend_to_opportunity", "signal_to_experiment"], "合并公开、平台和内部信号并保持权威等级。")
    add("ozon_activity_rules", "Ozon 活动/类目规则包", "market_research", "governance_control", "OzonRulePack", "ready", "product_architecture", ["trend_to_opportunity", "content_to_listing"], "将已核验官方活动和类目规则版本化，不依赖页面猜测。", platforms=["ozon"], markets=["RU"])
    add("keyword_demand_clustering", "俄语关键词需求聚类", "market_research", "research_ingest", "DemandCluster", "ready", "product_architecture", ["trend_to_opportunity"], "以来源、时间窗、语言和类目分组需求线索。", markets=["RU"])
    add("competitor_signal_watch", "竞品变化监测", "competitor_monitoring", "research_ingest", "CompetitorSignal", "ready", "product_architecture", ["signal_to_experiment"], "监测价格、内容和结构变化但不伪造销量或收入。")
    add("supplier_discovery", "供应商候选发现", "sourcing_1688", "research_ingest", "SupplierCandidate", "ready", "product_architecture", ["opportunity_to_supplier"], "公开供应商信息只进入候选池，待资质与联系验证。", platforms=["1688", "internal"])
    add("supplier_rfq_package", "结构化 RFQ 包", "sourcing_1688", "deterministic_transform", "SupplierRfqPackage", "implemented", "repository_verified", ["opportunity_to_supplier"], "冻结规格、数量阶梯、包装、文件、目的地和期限。")
    add("rfq_dispatch_proof", "RFQ 发送证明", "sourcing_1688", "human_review", "SupplierRfqDispatch", "implemented", "repository_verified", ["opportunity_to_supplier"], "原文、供应商、会话、时间和原始证明经另一身份复核。")
    add("supplier_response_capture", "供应商回复捕获", "sourcing_1688", "research_ingest", "SupplierResponseEvidence", "implemented", "repository_verified", ["opportunity_to_supplier"], "回复引用同一 Product/RFQ/供应商并保留原件。")
    add("supplier_quote_review", "供应商报价权威复核", "sourcing_1688", "human_review", "SupplierQuoteEvidence", "implemented", "repository_verified", ["opportunity_to_supplier", "supplier_to_unit_economics"], "非上传者核对供应商、规格、金额、MOQ、有效期和条款。")
    add("three_offer_comparison", "三报价比较", "sourcing_1688", "financial_projection", "SupplierOfferComparison", "implemented", "repository_verified", ["supplier_to_unit_economics", "demand_to_replenishment"], "只比较三份独立、当前、已接受报价。")
    add("logistics_route_quote", "物流线路报价", "inventory_orders_logistics_returns", "financial_projection", "LogisticsQuoteSnapshot", "implemented", "repository_verified", ["supplier_to_unit_economics"], "按实测重量尺寸、计费重、有效期和线路档位计算估算。")
    add("full_landed_cost", "15 项全成本", "full_cost_cm3", "financial_projection", "FullLandedCost", "implemented", "repository_verified", ["supplier_to_unit_economics"], "统一采购、物流、平台费、广告、退货、税费和资金成本。")
    add("cm3_projection", "CM3 投影", "full_cost_cm3", "financial_projection", "ContributionMarginSnapshot", "implemented", "repository_verified", ["supplier_to_unit_economics"], "输出来源等级、敏感性和缺口，不把 estimate 冒充 actual。")
    add("price_corridor", "价格走廊与盈亏门", "full_cost_cm3", "financial_projection", "PriceCorridor", "ready", "product_architecture", ["supplier_to_unit_economics"], "结合目标 CM3、平台约束和不确定区间给出可审查价格带。")
    add("ozon_catalog_read", "Ozon 目录只读采集", "listing_generation", "platform_read", "OzonCatalogSnapshot", "implemented", "repository_verified", ["product_to_passport", "listing_to_publish"], "使用已有 Ozon 只读合同采集目录并保留原始 Evidence。", platforms=["ozon"], markets=["RU"])
    add("listing_draft_generate", "Listing 草稿生成", "listing_generation", "generative_candidate", "ListingDraft", "implemented", "repository_verified", ["content_to_listing", "listing_to_publish"], "只从 Passport、合规规则和已批准内容生成结构化草稿。", platforms=["ozon"], markets=["RU"])
    add("listing_policy_lint", "Listing 规则与事实校验", "listing_generation", "governance_control", "ListingPolicyReport", "implemented", "repository_verified", ["content_to_listing", "listing_to_publish"], "确定性校验必填、枚举、敏感词、事实引用和媒体 manifest。", platforms=["ozon"], markets=["RU"])
    add("listing_human_approval", "Listing 人工批准", "listing_generation", "human_review", "ListingApproval", "implemented", "repository_verified", ["content_to_listing", "listing_to_publish"], "具名复核者批准精确草稿哈希、作用域和有效期。", platforms=["ozon"], markets=["RU"])
    add("execution_permit", "执行许可证", "controlled_execution", "governance_control", "ExecutionPermit", "implemented", "repository_verified", ["listing_to_publish", "exception_to_human_control"], "从批准决定签发短时、最小作用域、可撤销 Permit。")
    add("ozon_listing_write", "Ozon Listing 受控写入", "controlled_execution", "controlled_write", "OzonListingCommand", "implemented", "repository_verified", ["listing_to_publish"], "专用 Worker 在 Permit、幂等、预算和 Kill Switch 门内执行。", platforms=["ozon"], markets=["RU"])
    add("platform_readback", "平台独立回读", "controlled_execution", "platform_read", "PlatformReadbackReceipt", "implemented", "repository_verified", ["listing_to_publish", "publish_to_growth", "order_to_delivery"], "独立只读身份复验外部状态并形成回读收据。", platforms=["ozon"], markets=["RU"])
    add("ad_diagnostic", "广告只读诊断", "ads_and_causal_growth", "platform_read", "AdvertisingDiagnostic", "implemented", "repository_verified", ["publish_to_growth"], "读取已有 Evidence 诊断曝光、点击、转化与花费缺口。", platforms=["ozon"], markets=["RU"])
    add("experiment_hypothesis", "因果实验假设", "ads_and_causal_growth", "generative_candidate", "ExperimentHypothesis", "implemented", "repository_verified", ["publish_to_growth", "signal_to_experiment"], "把信号转成可证伪假设、指标、样本和停止条件。")
    add("shadow_budget", "影子预算与风险门", "ads_and_causal_growth", "governance_control", "ExperimentBudget", "ready", "product_architecture", ["publish_to_growth", "signal_to_experiment"], "先影子评估，显式限制资金、流量、时间和库存敞口。")
    add("causal_readout", "实验因果读数", "ads_and_causal_growth", "financial_projection", "ExperimentReadout", "ready", "product_architecture", ["publish_to_growth", "signal_to_experiment"], "区分相关与因果，记录样本、置信区间、停止原因和决策。")
    add("inventory_demand_signal", "库存需求信号", "inventory_orders_logistics_returns", "deterministic_transform", "InventoryDemandSignal", "implemented", "repository_verified", ["demand_to_replenishment", "order_to_delivery"], "合并当前库存、在途、销量和安全库存，不造历史曲线。")
    add("replenishment_decision", "补货建议与风险", "inventory_orders_logistics_returns", "generative_candidate", "ReplenishmentRecommendation", "implemented", "repository_verified", ["demand_to_replenishment"], "输出建议、假设、缺口和最坏情景，采购仍需批准。")
    add("purchase_order_approval", "采购单批准", "inventory_orders_logistics_returns", "human_review", "PurchaseApproval", "ready", "product_architecture", ["demand_to_replenishment"], "复核供应商、数量、价格、CM3、现金和交期后才允许采购。")
    add("order_ingest", "Ozon 订单只读接入", "inventory_orders_logistics_returns", "platform_read", "MarketplaceOrder", "implemented", "repository_verified", ["order_to_delivery"], "以现有订单合同规范化订单状态并保留原始响应。", platforms=["ozon"], markets=["RU"])
    add("delivery_monitor", "履约/物流状态监测", "inventory_orders_logistics_returns", "platform_read", "DeliveryEpisode", "implemented", "repository_verified", ["order_to_delivery", "delivery_to_return_support"], "追踪状态变化、超时和责任边界，不替代承运商权威。", platforms=["ozon"], markets=["RU"])
    add("return_case", "退货与售后案例", "inventory_orders_logistics_returns", "deterministic_transform", "ReturnCase", "implemented", "repository_verified", ["delivery_to_return_support"], "关联订单、原因、证据、库存影响、费用和处理决定。", platforms=["ozon"], markets=["RU"])
    add("finance_transaction_ingest", "财务交易采集", "finance_reconciliation", "platform_read", "FinanceTransaction", "implemented", "repository_verified", ["settlement_to_reconciliation"], "使用已有 Ozon 财务交易合同采集原始 Evidence。", platforms=["ozon"], markets=["RU"])
    add("fee_accrual_normalize", "费用/计提规范化", "finance_reconciliation", "financial_projection", "FeeAccrual", "implemented", "repository_verified", ["settlement_to_reconciliation"], "规范化服务费、物流、广告、退货、补贴与税务语义。", platforms=["ozon"], markets=["RU"])
    add("settlement_match", "结算逐项匹配", "finance_reconciliation", "financial_projection", "SettlementMatch", "implemented", "repository_verified", ["settlement_to_reconciliation"], "按订单、交易、结算和银行证据逐项对账。", platforms=["ozon"], markets=["RU"])
    add("fx_authority", "权威 FX 固化", "finance_reconciliation", "financial_projection", "FxRateSnapshot", "implemented", "repository_verified", ["supplier_to_unit_economics", "settlement_to_reconciliation"], "固化来源、币对、有效时间和 Decimal 汇率。")
    add("reconciliation_exception", "对账差异队列", "finance_reconciliation", "human_review", "ReconciliationException", "implemented", "repository_verified", ["settlement_to_reconciliation", "exception_to_human_control"], "记录金额、原因、Owner、截止期和关闭 Evidence。")

    # 10 · Cross-cutting control and global adapter plane.
    add("evidence_ledger_append", "Evidence 账本追加", "evidence_lineage", "governance_control", "EvidenceRecord", "implemented", "repository_verified", ["product_to_passport", "exception_to_human_control"], "所有外部/人工输入先形成不可变 Evidence。")
    add("lineage_edge_validate", "血缘边校验", "evidence_lineage", "governance_control", "LineageEdge", "implemented", "repository_verified", ["product_to_passport", "exception_to_human_control"], "验证来源、派生、替代和复核关系不悬空。")
    add("approval_separation", "职责分离审批", "controlled_execution", "human_review", "ApprovalDecision", "implemented", "repository_verified", ["listing_to_publish", "delivery_to_return_support", "exception_to_human_control"], "禁止提交者批准自己的高风险对象。")
    add("execution_scope_guard", "执行作用域守卫", "controlled_execution", "governance_control", "ExecutionScope", "implemented", "repository_verified", ["demand_to_replenishment", "exception_to_human_control"], "在 endpoint、角色、店铺、对象、预算和时间上执行最小权限。")
    add("external_write_kill_switch", "外部写 Kill Switch", "controlled_execution", "governance_control", "KillSwitchState", "implemented", "repository_verified", ["exception_to_human_control"], "风险事件时全局阻断生产外部写入。")
    add("readback_receipt", "回读收据", "controlled_execution", "deterministic_transform", "ReadbackReceipt", "implemented", "repository_verified", ["listing_to_publish", "exception_to_human_control"], "比较期望、平台实际和差异，绑定独立读 Evidence。")
    add("rollback_compensation", "回滚与补偿", "controlled_execution", "controlled_write", "CompensationCommand", "implemented", "repository_verified", ["exception_to_human_control"], "在允许且安全时执行补偿，否则冻结并转人工。")
    add("schema_drift_guard", "Schema 漂移守卫", "global_platform_adapters", "governance_control", "SchemaDriftReport", "implemented", "repository_verified", ["exception_to_human_control"], "固定样本、字段、枚举和语义变化失败关闭。")
    add("adapter_admission", "平台适配器准入", "global_platform_adapters", "governance_control", "AdapterAdmission", "gated", "product_architecture", ["exception_to_human_control"], "官方合同、许可、身份、样本、回放、限流、撤销和回滚齐备后准入。")
    add("market_rule_pack", "国家/平台规则包", "global_platform_adapters", "governance_control", "MarketRulePack", "ready", "product_architecture", ["product_to_passport", "content_to_listing"], "隔离市场、平台、类目、有效期、优先级和冲突。")
    add("language_localization_pack", "语言本地化包", "global_platform_adapters", "deterministic_transform", "LocalizationPack", "ready", "product_architecture", ["passport_to_content", "content_to_listing"], "术语、语气、复数、单位、脚本和母语复核可版本化。")
    add("currency_tax_pack", "币种/税务包", "global_platform_adapters", "financial_projection", "FinanceMarketPack", "ready", "product_architecture", ["supplier_to_unit_economics", "settlement_to_reconciliation"], "隔离币种、FX 权威、税务规则和舍入语义。")
    add("model_provider_router", "模型提供方路由", "model_and_skill_observability", "governance_control", "ModelRouteDecision", "ready", "product_architecture", ["passport_to_content", "exception_to_human_control"], "按任务、质量、许可、地域、成本和故障选择可替换模型。")
    add("model_skill_eval", "模型/Skill 评测", "model_and_skill_observability", "governance_control", "EvaluationRun", "implemented", "repository_verified", ["passport_to_content", "exception_to_human_control"], "金标、轨迹、工具调用、质量、成本和回归门共同准入。")
    add("cost_latency_observability", "成本/延迟/质量遥测", "model_and_skill_observability", "governance_control", "ModelTelemetry", "implemented", "repository_verified", ["passport_to_content", "exception_to_human_control"], "记录模型/Skill 版本、延迟、token/算力、QA 与人工结论。")
    add("audit_export", "全链路审计导出", "evidence_lineage", "content_delivery", "AuditBundle", "ready", "product_architecture", ["settlement_to_reconciliation", "exception_to_human_control"], "导出对象、Evidence、决策、执行、回读、异常和关闭证明。")

    stream_specs = [
        {
            "id": "trend_to_opportunity",
            "label": "趋势 → 可验证机会",
            "mission": "把公开趋势和内部观察变成有来源、有假设、有淘汰条件的机会卡。",
            "stage_point_ids": ["trend_event_calendar", "inspiration_signal_capture", "market_signal_inbox", "keyword_demand_clustering", "evidence_grounded_analysis", "product_profile_agent"],
            "object_transitions": ["RawEvidence → ResearchSignal", "ResearchSignal → DemandCluster", "DemandCluster → OpportunityCandidate"],
            "entry_gate": "来源、时间、许可和市场范围完整。",
            "exit_gate": "机会卡包含事实/推断/未知、目标用户、价格假设和否决条件。",
            "events": ["research.signal.accepted", "opportunity.candidate.created"],
            "exceptions": ["来源过期", "许可未知", "信号冲突", "无可证伪假设"],
            "human_takeover": "市场研究 Owner 复核 C 级信号和机会晋级。",
            "kpi": ["信号到机会转化率", "证据完整率", "机会淘汰提前量"],
            "sla": "每周机会评审；高时效活动 24h",
            "adapter_boundary": "公开站点只读采集；平台账户事实必须走已准入 read adapter。",
        },
        {
            "id": "opportunity_to_supplier",
            "label": "机会 → 供应商事实",
            "mission": "把商品机会变成可追溯 RFQ、发送证明、回复和权威报价。",
            "stage_point_ids": ["product_profile_agent", "supplier_discovery", "supplier_rfq_package", "rfq_dispatch_proof", "supplier_response_capture", "supplier_quote_review"],
            "object_transitions": ["OpportunityCandidate → SupplierCandidate", "SupplierCandidate → SupplierRfqPackage", "DispatchEvidence → AcceptedSupplierQuote"],
            "entry_gate": "商品规格、数量阶梯、目的地和截止期可冻结。",
            "exit_gate": "至少三份不同供应商、当前有效、经非上传者接受的报价。",
            "events": ["supplier.rfq.packaged", "supplier.dispatch.accepted", "supplier.quote.accepted"],
            "exceptions": ["供应商身份不明", "规格不一致", "发送证明不足", "报价过期"],
            "human_takeover": "采购 Owner 与独立复核人处理身份、规格和报价权威。",
            "kpi": ["有效回复率", "报价完整率", "三报价形成周期"],
            "sla": "RFQ 24h 内发出；报价到达后 1 个工作日复核",
            "adapter_boundary": "不自动联系供应商；任何消息发送必须有显式授权和证明。",
        },
        {
            "id": "supplier_to_unit_economics",
            "label": "供应商事实 → CM3 单位经济",
            "mission": "把报价、物流、FX 和平台费用转成分层权威的全成本与 CM3。",
            "stage_point_ids": ["supplier_quote_review", "three_offer_comparison", "logistics_route_quote", "full_landed_cost", "fx_authority", "cm3_projection", "price_corridor"],
            "object_transitions": ["AcceptedSupplierQuote → SupplierOfferComparison", "Quote+Route+FX → FullLandedCost", "FullLandedCost → ContributionMarginSnapshot"],
            "entry_gate": "报价与物流来源、币种、有效期和规格一致。",
            "exit_gate": "CM3 标明 estimate/actual/reconciled、缺口、敏感性和批准阈值。",
            "events": ["supplier.offers.compared", "cm3.snapshot.created"],
            "exceptions": ["FX 过期", "费用漏项", "规格不一致", "CM3 低于门槛"],
            "human_takeover": "财务复核关键费用和 FX；经营 Owner 决定价格/淘汰。",
            "kpi": ["成本完整率", "预测/实际偏差", "CM3 门通过率"],
            "sla": "来源变更后 1h 内使旧快照过期",
            "adapter_boundary": "物流报价保持 estimate；最终账单须经独立权威复核。",
        },
        {
            "id": "product_to_passport",
            "label": "商品身份 → 可引用 Passport",
            "mission": "建立商品、平台身份、合规、品牌、权利和供应事实的统一引用面。",
            "stage_point_ids": ["catalog_csv_import", "ozon_catalog_read", "canonical_product_identity", "external_listing_identity_map", "product_passport_assembly", "brand_token_registry", "sensitive_term_rulepack", "asset_rights_scope"],
            "object_transitions": ["CatalogEvidence → CanonicalProduct", "ExternalListing → ExternalIdentityMap", "EvidenceSet → ProductPassport"],
            "entry_gate": "来源 Evidence、店铺/offer 作用域和人工绑定确认完整。",
            "exit_gate": "Passport 版本、事实来源、未知、权利和合规有效期可审查。",
            "events": ["product.identity.bound", "product.passport.versioned"],
            "exceptions": ["重复身份", "平台映射冲突", "合规原件缺失", "素材权利未知"],
            "human_takeover": "商品 Owner 与合规复核人处理身份和高风险字段。",
            "kpi": ["Passport 完整率", "身份冲突数", "权利覆盖率"],
            "sla": "关键来源变更后同步使下游候选过期",
            "adapter_boundary": "Ozon 首先只读；第二平台复用 Canonical Product，不复制真源。",
        },
        {
            "id": "passport_to_content",
            "label": "Passport → 多模态内容交付",
            "mission": "把商品真源变成已核权、已 QA、已批准、可重放的图片/视频/文案资产。",
            "stage_point_ids": ["product_passport_assembly", "objective_interpreter", "product_image_suite", "apparel_image_suite", "design_canvas", "image_to_video", "garment_fidelity_qa", "design_preflight", "media_delivery_manifest"],
            "object_transitions": ["ProductPassport → StructuredBrief", "StructuredBrief → ContentCandidate", "ApprovedCandidate → ContentDeliveryManifest"],
            "entry_gate": "Passport、素材权利、品牌、市场和平台 profile 有效。",
            "exit_gate": "每项资产通过商品保真、OCR、合规、权利、人工批准与 manifest。",
            "events": ["content.candidate.generated", "content.asset.approved", "content.manifest.sealed"],
            "exceptions": ["商品漂移", "俄语错误", "权利未知", "模型成本超限", "批次部分失败"],
            "human_takeover": "设计/内容 Owner 和 RU 母语复核者批准逐资产产物。",
            "kpi": ["一次验收率", "商品保真率", "单资产成本", "批次部分失败率"],
            "sla": "任何源事实变化立即标记关联候选 stale",
            "adapter_boundary": "模型提供方可替换；不得被授予商品事实或平台写权限。",
        },
        {
            "id": "content_to_listing",
            "label": "内容交付 → Listing 草稿",
            "mission": "把批准内容和 Passport 编译成平台规则可验证的结构化 Listing 草稿。",
            "stage_point_ids": ["media_delivery_manifest", "image_translation", "multilingual_glossary", "listing_draft_generate", "listing_policy_lint", "listing_human_approval"],
            "object_transitions": ["ContentManifest+Passport → ListingDraft", "ListingDraft → PolicyReport", "PolicyReport → ListingApproval"],
            "entry_gate": "内容 manifest、Passport、规则包与术语版本当前有效。",
            "exit_gate": "精确草稿哈希由独立身份批准，且所有阻断项清零。",
            "events": ["listing.draft.generated", "listing.policy.passed", "listing.approved"],
            "exceptions": ["必填缺失", "枚举漂移", "事实引用断裂", "媒体过期", "敏感表达"],
            "human_takeover": "类目运营和 RU 合规复核 Listing 精确版本。",
            "kpi": ["规则一次通过率", "草稿返工率", "事实引用完整率"],
            "sla": "草稿规则同步校验；人工复核 24h",
            "adapter_boundary": "平台规则 profile 版本化；未核验字段不猜测。",
        },
        {
            "id": "listing_to_publish",
            "label": "Listing 批准 → 受控发布与回读",
            "mission": "把已批准 Listing 经 Permit、最小权限、幂等、回读和补偿安全落到 Ozon。",
            "stage_point_ids": ["ozon_catalog_read", "listing_draft_generate", "listing_policy_lint", "listing_human_approval", "approval_separation", "execution_permit", "ozon_listing_write", "platform_readback", "readback_receipt"],
            "object_transitions": ["ListingApproval → ExecutionPermit", "Permit+Draft → PlatformReceipt", "PlatformReceipt+ReadEvidence → ReadbackReceipt"],
            "entry_gate": "批准、Permit、幂等、作用域、预算和 Kill Switch 均有效。",
            "exit_gate": "独立回读与期望状态一致；否则冻结、补偿或转人工。",
            "events": ["execution.permit.issued", "listing.write.attempted", "listing.readback.verified"],
            "exceptions": ["平台拒绝", "部分成功", "回读不一致", "Permit 过期", "Kill Switch engaged"],
            "human_takeover": "风险/运营 Owner 决定补偿、重试或冻结。",
            "kpi": ["批准写入成功率", "回读一致率", "越权拦截数", "补偿成功率"],
            "sla": "写入后立即回读；不一致立即冻结",
            "adapter_boundary": "当前只承认仓库已测试 Ozon 合同；其他平台必须重新准入。",
        },
        {
            "id": "publish_to_growth",
            "label": "发布状态 → 广告与增长实验",
            "mission": "把平台回读、广告诊断和市场信号转成受预算约束的可证伪增长实验。",
            "stage_point_ids": ["platform_readback", "ad_diagnostic", "experiment_hypothesis", "shadow_budget", "causal_readout"],
            "object_transitions": ["PlatformReadback → GrowthDiagnostic", "Diagnostic → ExperimentHypothesis", "ExperimentEvidence → CausalReadout"],
            "entry_gate": "基线、目标指标、样本、预算和停止条件完整。",
            "exit_gate": "结论明确相关/因果、置信度、适用范围和下一决定。",
            "events": ["growth.diagnostic.created", "experiment.hypothesis.approved", "experiment.readout.created"],
            "exceptions": ["无基线", "样本不足", "预算超限", "库存风险", "指标漂移"],
            "human_takeover": "增长 Owner 批准真实实验和预算；影子阶段不得写外部平台。",
            "kpi": ["有效实验率", "增量 CM3", "停止规则命中率"],
            "sla": "实验达到停止条件后 24h 内复盘",
            "adapter_boundary": "广告写入未独立准入时保持诊断/建议只读。",
        },
        {
            "id": "demand_to_replenishment",
            "label": "需求/库存 → 补货与采购批准",
            "mission": "把库存、需求、在途、三报价和现金边界变成可批准的补货决定。",
            "stage_point_ids": ["inventory_demand_signal", "replenishment_decision", "three_offer_comparison", "cm3_projection", "purchase_order_approval", "execution_scope_guard"],
            "object_transitions": ["InventoryEvidence → DemandSignal", "DemandSignal+CM3 → ReplenishmentRecommendation", "Recommendation → PurchaseApproval"],
            "entry_gate": "库存/在途/销量时间窗、供应报价、CM3 和现金限制可审查。",
            "exit_gate": "具名批准精确供应商、SKU、数量、价格和期限。",
            "events": ["inventory.demand.signal.created", "replenishment.recommended", "purchase.approved"],
            "exceptions": ["历史不足", "报价过期", "现金超限", "CM3 低", "库存风险"],
            "human_takeover": "采购与财务双重复核真实采购承诺。",
            "kpi": ["缺货风险", "周转天数", "预测偏差", "被避免的低 CM3 采购"],
            "sla": "高缺货风险每日复核",
            "adapter_boundary": "未建立受控采购发送通道前只产生批准合同，不自动下单。",
        },
        {
            "id": "order_to_delivery",
            "label": "订单 → 履约交付",
            "mission": "把 Ozon 订单、库存和物流状态串成可审查交付 Episode。",
            "stage_point_ids": ["order_ingest", "inventory_demand_signal", "delivery_monitor", "platform_readback"],
            "object_transitions": ["MarketplaceOrder → DeliveryEpisode", "DeliveryStatus → InventoryImpact", "PlatformReadEvidence → DeliveryReadback"],
            "entry_gate": "订单来源、店铺、SKU、金额和状态版本有效。",
            "exit_gate": "交付或异常结论有平台/物流 Evidence 与库存影响。",
            "events": ["order.observed", "delivery.status.changed", "delivery.exception.opened"],
            "exceptions": ["订单漂移", "超时", "丢件", "库存不一致", "状态回退"],
            "human_takeover": "履约 Owner 处理超时、丢件和平台争议。",
            "kpi": ["按时交付率", "异常率", "状态新鲜度", "库存一致率"],
            "sla": "高风险物流异常 4h 内确认",
            "adapter_boundary": "平台/承运商状态保持各自权威，不由 AI 猜测。",
        },
        {
            "id": "delivery_to_return_support",
            "label": "交付 → 退货与售后",
            "mission": "将订单、交付、退货原因、客户沟通、库存和费用形成闭环案例。",
            "stage_point_ids": ["delivery_monitor", "return_case", "localized_script_voice", "approval_separation"],
            "object_transitions": ["DeliveryEpisode → ReturnCase", "ReturnEvidence → ResolutionDecision", "Resolution → Inventory+FinanceImpact"],
            "entry_gate": "订单、商品、原因和客户/平台证据关联完整。",
            "exit_gate": "处理决定、沟通、库存、费用和关闭证据均记录。",
            "events": ["return.case.opened", "return.resolution.approved", "return.case.closed"],
            "exceptions": ["原因不明", "证据不足", "高价值争议", "库存/退款不一致"],
            "human_takeover": "客服/风险 Owner 决定赔付、申诉和高风险沟通。",
            "kpi": ["退货率", "首次解决率", "关闭周期", "原因可归因率"],
            "sla": "客户/平台期限前完成下一动作",
            "adapter_boundary": "AI 只生成候选回复；发送和赔付需独立授权。",
        },
        {
            "id": "settlement_to_reconciliation",
            "label": "交易/结算 → 财务对账",
            "mission": "把 Ozon 交易、费用、结算、银行与 FX 逐项匹配到权威财务结论。",
            "stage_point_ids": ["finance_transaction_ingest", "fee_accrual_normalize", "settlement_match", "fx_authority", "reconciliation_exception", "audit_export"],
            "object_transitions": ["RawFinanceEvidence → FinanceTransaction", "Transaction+Fee → SettlementMatch", "Difference → ReconciliationException"],
            "entry_gate": "交易、结算、币种、时间和来源权威可识别。",
            "exit_gate": "每笔金额 matched/exception，差异有 Owner、期限和关闭 Evidence。",
            "events": ["finance.transaction.observed", "settlement.matched", "reconciliation.exception.closed"],
            "exceptions": ["缺交易", "重复费用", "金额差异", "FX 不一致", "银行证据缺失"],
            "human_takeover": "财务 Owner 复核金额并关闭差异，AI 不签署财务事实。",
            "kpi": ["对账覆盖率", "未对账金额", "差异队列年龄", "预测/实际偏差"],
            "sla": "关键差异 T+1；其余按结算周期",
            "adapter_boundary": "只有平台/银行原始文件与独立复核可晋升 actual/reconciled。",
        },
        {
            "id": "signal_to_experiment",
            "label": "经营信号 → 学习实验",
            "mission": "把竞品、市场和经营信号转成有预算、有金标、有停止条件的学习循环。",
            "stage_point_ids": ["competitor_signal_watch", "market_signal_inbox", "evidence_grounded_analysis", "experiment_hypothesis", "shadow_budget", "causal_readout"],
            "object_transitions": ["Signal → AnalysisCandidate", "Analysis → ExperimentHypothesis", "ExperimentEvidence → LearningDecision"],
            "entry_gate": "信号来源、基线、可控变量和目标指标存在。",
            "exit_gate": "决策明确采用/拒绝/继续研究及其适用边界。",
            "events": ["signal.analysis.created", "experiment.shadow.completed", "learning.decision.recorded"],
            "exceptions": ["不可证伪", "数据泄漏", "样本不足", "成本超限"],
            "human_takeover": "经营/数据 Owner 批准真实实验和学习结论。",
            "kpi": ["信号到实验率", "被否决假设数", "有效学习周期", "增量 CM3"],
            "sla": "每周复盘；高成本实验需预审",
            "adapter_boundary": "公开竞品数据保持 C 级，不能作为销量真值。",
        },
        {
            "id": "exception_to_human_control",
            "label": "异常 → 人工控制与恢复",
            "mission": "统一处理 schema、权限、模型、执行、财务和数据异常，避免静默失败。",
            "stage_point_ids": ["schema_drift_guard", "reconciliation_exception", "model_skill_eval", "approval_separation", "external_write_kill_switch", "rollback_compensation", "audit_export"],
            "object_transitions": ["ControlFailure → ExceptionCase", "ExceptionCase → HumanDecision", "Decision → RecoveryOrFreeze"],
            "entry_gate": "异常分类、受影响对象、严重度、Owner 和原始轨迹完整。",
            "exit_gate": "恢复/冻结/回滚结论有 readback 与关闭 Evidence。",
            "events": ["control.exception.opened", "kill_switch.engaged", "exception.recovered"],
            "exceptions": ["Owner 缺失", "轨迹不完整", "补偿失败", "重复故障"],
            "human_takeover": "风险 Owner 对高严重度异常拥有冻结与恢复决定权。",
            "kpi": ["异常队列年龄", "MTTR", "重复故障率", "无 Owner 异常数"],
            "sla": "P0 立即冻结；P1 4h；P2 24h",
            "adapter_boundary": "任何第三方故障不降低内部最小权限和 Evidence 门。",
        },
    ]

    for stream in stream_specs:
        members = [point["id"] for point in points if stream["id"] in point["value_stream_ids"]]
        stages = set(stream["stage_point_ids"])
        stream["supporting_point_ids"] = [point_id for point_id in members if point_id not in stages]

    surfaces = [
        {
            "id": "store_operating_matrix",
            "label": "店铺经营矩阵面",
            "mission": "按店铺×市场×平台×类目×商品×时间统一查看状态、增长、履约和财务。",
            "value_stream_ids": ["listing_to_publish", "publish_to_growth", "demand_to_replenishment", "order_to_delivery", "settlement_to_reconciliation"],
            "focus_point_ids": ["external_listing_identity_map", "ozon_catalog_read", "platform_readback", "order_ingest", "settlement_match"],
            "dimensions": ["store", "market", "platform", "category", "product", "time"],
            "decisions": ["哪些店铺/商品需要人工处理", "哪里存在发布/库存/履约/对账阻断", "增长是否增加真实 CM3"],
            "truth_owner": "Canonical Product + 平台 Read Evidence + Finance Reconciliation",
            "kpi": ["在线 Listing 覆盖", "回读一致率", "缺货风险", "按时交付率", "已对账 CM3"],
            "alerts": ["平台状态漂移", "库存负数/过期", "履约超时", "未对账金额超阈值"],
            "write_boundary": "本面只读聚合；任何外部动作跳转到原工作区并重新验证角色、批准和 Permit。",
        },
        {
            "id": "product_truth_surface",
            "label": "商品真源与 Passport 面",
            "mission": "显示商品身份、平台映射、规格、权利、品牌、合规和来源的当前版本与缺口。",
            "value_stream_ids": ["product_to_passport", "supplier_to_unit_economics"],
            "focus_point_ids": ["canonical_product_identity", "external_listing_identity_map", "product_passport_assembly", "asset_rights_scope", "cm3_projection"],
            "dimensions": ["global_product", "sku_episode", "store", "market", "passport_type", "version"],
            "decisions": ["事实是否足以生成内容/Listing", "哪些字段或权利已过期", "哪个平台身份发生冲突"],
            "truth_owner": "Product + Evidence + Passport 聚合",
            "kpi": ["Passport 完整率", "事实引用覆盖率", "权利覆盖率", "身份冲突数"],
            "alerts": ["来源变更导致下游 stale", "权利过期", "合规原件缺失", "平台映射冲突"],
            "write_boundary": "人工确认只能通过现有 Product/Passport 工作区；图谱不修改商品事实。",
        },
        {
            "id": "content_factory_surface",
            "label": "多模态内容工厂面",
            "mission": "统筹文案、图片、服装、设计、POD、修图、视频、批次、QA 和交付。",
            "value_stream_ids": ["passport_to_content", "content_to_listing"],
            "focus_point_ids": ["product_image_suite", "apparel_image_suite", "smart_repair", "image_to_video", "media_delivery_manifest"],
            "dimensions": ["product", "asset_type", "locale", "platform_profile", "model_skill_version", "batch"],
            "decisions": ["哪个候选可进入交付", "返工由事实/权利/质量/语言哪一类驱动", "哪个模型/Skill 值得晋级"],
            "truth_owner": "Product Passport + Asset Rights + Content Manifest",
            "kpi": ["一次验收率", "商品保真率", "俄语通过率", "单资产成本", "批次失败率"],
            "alerts": ["商品漂移", "权利未知", "OCR/敏感词失败", "模型回归", "成本/并发超限"],
            "write_boundary": "生成只产生候选；批准与平台发布分离。",
        },
        {
            "id": "controlled_execution_surface",
            "label": "受控执行与异常面",
            "mission": "统一查看批准、Permit、外部写、回读、Kill Switch、回滚和异常恢复。",
            "value_stream_ids": ["listing_to_publish", "exception_to_human_control"],
            "focus_point_ids": ["approval_separation", "execution_permit", "ozon_listing_write", "readback_receipt", "external_write_kill_switch", "rollback_compensation"],
            "dimensions": ["store", "endpoint", "actor", "permit", "object", "risk_severity", "time"],
            "decisions": ["是否允许执行", "何时冻结/回滚", "异常由谁接管", "读回是否证明完成"],
            "truth_owner": "Approval + Execution + Readback + Audit",
            "kpi": ["越权拦截数", "回读一致率", "补偿成功率", "MTTR", "Permit 过期率"],
            "alerts": ["无 Permit 写入尝试", "回读不一致", "Kill Switch 状态异常", "重复故障"],
            "write_boundary": "只有独立受限 Worker 可写；面板本身保持只读。",
        },
        {
            "id": "supply_profit_surface",
            "label": "供应、库存与利润面",
            "mission": "从供应商事实到物流、全成本、CM3、库存和采购决定统一审视风险。",
            "value_stream_ids": ["opportunity_to_supplier", "supplier_to_unit_economics", "demand_to_replenishment", "settlement_to_reconciliation"],
            "focus_point_ids": ["supplier_quote_review", "three_offer_comparison", "full_landed_cost", "cm3_projection", "inventory_demand_signal", "settlement_match"],
            "dimensions": ["product", "supplier", "route", "currency", "cost_authority", "inventory_episode", "settlement"],
            "decisions": ["供应商/路线如何选择", "价格与采购量是否满足 CM3/现金门", "预测与实际差异在哪里"],
            "truth_owner": "Supplier Evidence + Cost Snapshot + Inventory + Reconciliation",
            "kpi": ["三报价覆盖率", "CM3", "周转天数", "缺货风险", "预测/实际偏差"],
            "alerts": ["报价/FX 过期", "CM3 低于阈值", "库存风险", "未对账金额"],
            "write_boundary": "补货/采购建议不等于采购承诺；必须由现有审批链执行。",
        },
        {
            "id": "customer_after_sales_surface",
            "label": "订单、履约与售后面",
            "mission": "串联订单、交付、退货、沟通、库存和费用影响。",
            "value_stream_ids": ["order_to_delivery", "delivery_to_return_support"],
            "focus_point_ids": ["order_ingest", "delivery_monitor", "return_case", "localized_script_voice", "approval_separation"],
            "dimensions": ["order", "product", "customer_case", "delivery_episode", "return_reason", "region", "time"],
            "decisions": ["哪一单需要接管", "退货根因是什么", "如何沟通/申诉/赔付", "库存与财务如何更新"],
            "truth_owner": "Order/Delivery/Return Evidence",
            "kpi": ["按时交付率", "退货率", "首次解决率", "案例关闭周期"],
            "alerts": ["物流超时", "高价值争议", "重复退货原因", "退款/库存不一致"],
            "write_boundary": "AI 只生成回复候选；发送、赔付和申诉需授权。",
        },
        {
            "id": "agent_skill_surface",
            "label": "Agent、Skill 与模型治理面",
            "mission": "查看任务计划、工具、模型、评测、预算、轨迹、人工结论和外部 Worker 准入。",
            "value_stream_ids": ["trend_to_opportunity", "passport_to_content", "signal_to_experiment", "exception_to_human_control"],
            "focus_point_ids": ["objective_interpreter", "skill_plan_builder", "model_provider_router", "model_skill_eval", "cost_latency_observability", "claw_worker_admission"],
            "dimensions": ["objective", "agent", "skill", "model", "tool", "eval_set", "store", "risk"],
            "decisions": ["哪个模型/Skill 可进入影子或生产", "成本/延迟/质量是否达标", "何时人工接管或撤销"],
            "truth_owner": "Agent Plan + Eval Run + Telemetry + Approval",
            "kpi": ["评测通过率", "工具调用成功率", "人工接管率", "单任务成本", "回归数"],
            "alerts": ["未评测 Skill", "工具越权", "成本超限", "质量回归", "轨迹缺失"],
            "write_boundary": "Agent 不持有独立业务写权；每次工具调用仍受 endpoint 权限与 Permit。",
        },
        {
            "id": "global_expansion_surface",
            "label": "全球市场扩展面",
            "mission": "把 Russia/Ozon 已验证内核扩展为国家、平台、语言、币税和物流可替换适配器。",
            "value_stream_ids": ["product_to_passport", "content_to_listing", "listing_to_publish", "settlement_to_reconciliation", "exception_to_human_control"],
            "focus_point_ids": ["adapter_admission", "schema_drift_guard", "market_rule_pack", "language_localization_pack", "currency_tax_pack", "audit_export"],
            "dimensions": ["country", "platform", "locale", "currency", "tax_regime", "category", "adapter_version"],
            "decisions": ["新市场还缺哪些合同/样本/许可", "哪些内核可复用", "哪个适配器必须失败关闭"],
            "truth_owner": "Canonical Kernel + Versioned Market/Platform Adapters",
            "kpi": ["适配器准入通过率", "合同复用率", "schema 漂移拦截率", "本地化复核通过率"],
            "alerts": ["官方合同变化", "许可/凭证过期", "规则包冲突", "币税权威缺失"],
            "write_boundary": "除 Ozon 已验证合同外均保持 gated；每个平台独立准入，不继承 Ozon 权限。",
        },
    ]

    for stream in stream_specs:
        stream["workspace"] = f"/operations/lines/{stream['id']}"
    for surface in surfaces:
        surface["workspace"] = f"/operations/surfaces/{surface['id']}"

    graph = {
        "contract_id": "kjds-cross-border-operating-graph-v1",
        "model": "point-line-surface",
        "model_definition": {
            "point": "最小可审查经营/工具/控制能力，具备业务对象、输入输出、责任、Evidence、失败队列、回读和 KPI。",
            "line": "按业务对象状态变化排列的端到端价值流，具备入口/出口门、事件、异常、SLO 和人工接管。",
            "surface": "跨价值流的经营控制面，回答管理决策并声明维度、真源、指标、预警和写边界。",
        },
        "source_kinds": SOURCE_KINDS,
        "contract_profiles": PROFILES,
        "atomic_points": points,
        "value_streams": stream_specs,
        "operating_surfaces": surfaces,
    }
    validate_graph(graph, capability_index)
    return graph


def validate_graph(
    graph: dict[str, Any],
    capability_index: dict[str, tuple[str, dict[str, Any]]],
) -> None:
    point_ids = [point["id"] for point in graph["atomic_points"]]
    if len(point_ids) != len(set(point_ids)):
        raise ValueError("Atomic point ids must be unique")
    stream_ids = [stream["id"] for stream in graph["value_streams"]]
    if len(stream_ids) != len(set(stream_ids)):
        raise ValueError("Value stream ids must be unique")
    surface_ids = [surface["id"] for surface in graph["operating_surfaces"]]
    if len(surface_ids) != len(set(surface_ids)):
        raise ValueError("Operating surface ids must be unique")
    point_set = set(point_ids)
    stream_set = set(stream_ids)
    profile_set = set(PROFILES)
    for point in graph["atomic_points"]:
        if point["parent_capability_id"] not in capability_index:
            raise ValueError(f"Unknown parent for {point['id']}")
        if point["contract_profile_id"] not in profile_set:
            raise ValueError(f"Unknown profile for {point['id']}")
        if point["status"] not in STATUS:
            raise ValueError(f"Unknown status for {point['id']}")
        if not set(point["value_stream_ids"]) <= stream_set:
            raise ValueError(f"Unknown stream membership for {point['id']}")
        if point.get("workspace_id") not in DOMAIN_WORKSPACE_IDS:
            raise ValueError(f"Unknown workspace id for {point['id']}")
        if point.get("workspace") != f"/operations/points/{point['id']}":
            raise ValueError(f"Invalid point workspace for {point['id']}")
    for stream in graph["value_streams"]:
        refs = stream["stage_point_ids"] + stream["supporting_point_ids"]
        if not refs or not set(refs) <= point_set:
            raise ValueError(f"Unknown/empty point reference for {stream['id']}")
        if len(refs) != len(set(refs)):
            raise ValueError(f"Duplicate point reference for {stream['id']}")
        if stream.get("workspace") != f"/operations/lines/{stream['id']}":
            raise ValueError(f"Invalid line workspace for {stream['id']}")
    for surface in graph["operating_surfaces"]:
        if not set(surface["value_stream_ids"]) <= stream_set:
            raise ValueError(f"Unknown stream reference for {surface['id']}")
        if not set(surface["focus_point_ids"]) <= point_set:
            raise ValueError(f"Unknown point reference for {surface['id']}")
        if surface.get("workspace") != f"/operations/surfaces/{surface['id']}":
            raise ValueError(f"Invalid surface workspace for {surface['id']}")


def render_registry() -> str:
    atlas = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    atlas["registry_version"] = REGISTRY_VERSION
    atlas["operating_graph"] = build_graph(atlas)
    return json.dumps(atlas, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when the committed registry is not the deterministic build output.",
    )
    args = parser.parse_args()
    rendered = render_registry()
    if args.check:
        if REGISTRY_PATH.read_text(encoding="utf-8") != rendered:
            print(f"{REGISTRY_PATH} is stale; rebuild without --check")
            return 1
        print(f"{REGISTRY_PATH} is current")
        return 0
    REGISTRY_PATH.write_text(rendered, encoding="utf-8")
    graph = json.loads(rendered)["operating_graph"]
    print(
        "built",
        len(graph["atomic_points"]),
        "points,",
        len(graph["value_streams"]),
        "lines,",
        len(graph["operating_surfaces"]),
        "surfaces",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

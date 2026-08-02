# BAS-104 真实 scoped 目录解锁与通用证据作用域绑定（2026-08-02 延续）

| 项 | 值 |
|---|---|
| 分支 | `feature/batch-opportunity-mining-059` |
| 需求 | BR-082 / BR-084 / BAS-104 / BAS-108 |
| 状态 | IN_PROGRESS（目录链已解锁，观测/Passport 仍缺真实输入） |

## 本轮交付

### 通用 governed Evidence scope 绑定服务（工程缺口修复）

`ScopedEvidenceAuthority` 此前只能投影 `kjds-evidence-scope-binding-v1`
绑定，但生产环境没有通用路径为旧不可变证据补作用域（只有 seller-ERP 与
浏览器采集两条工作流专属路径）。新增 `EvidenceScopeBindingService`
（`apps/control_plane/evidence_scope_binding.py`）+ 三条 API：

- `POST /v1/evidence/scope-bindings`（operator/admin 提交绑定请求）
- `POST /v1/evidence/scope-bindings/{id}/review`（reviewer/compliance/risk/admin 独立评审）
- `POST /v1/evidence/scope-bindings/{id}/record`（compliance/admin 记录 grade-A 绑定）

严格 SoD：提交者/评审者/记录者/目标创建者四方独立；幂等重放；
已绑定目标拒绝二次记录。OpenAPI 快照已重新导出；回归
`tests/test_evidence_scope_binding.py`（2）+ 全量后端 `1266 passed`。

### 真实数据解锁（全部经真实 API 与真实证据）

- 真实 1688 观测证据 `evd_6d5e9c53…`（`detail.1688.com/offer/1045914391146.html`）
  经 owner 评审（kjds-owner-lunar）+ compliance 记录（r0-compliance）绑定 exact scope
  （binding `evd_d08546fe…`）；收件箱 `evidence_scope_binding_missing` 缺口消除，
  剩余 `variant_selection_unverified` 需重采精确变体。
- 真实 Ozon 商品回读原始响应证据 `evd_3f6f93b0…`（BAS-160 零环境凭据 run
  `ror_ea3193…` 的 raw response）绑定 exact scope（binding `evd_b1fc1267…`）。
- 真实 scoped 目录导入完成：handoff `crh_492e33…` `completed`，新 scoped
  catalog snapshot `mcs_e511d420…`（scope default/kjds/ozon-primary，
  `scope_evidence_authority_sha256=0eeac68b…`）。
- `POST /v1/batch-market-scans` 重跑：`catalog_items=1`，
  `catalog_evidence_scope_binding_missing` 与 `scoped_products_not_available`
  已消除；剩余真实缺口：`approved_passports_incomplete`、
  `approved_media_qa_incomplete`（Canonical Product 的 Passport/媒体 QA 门）、
  `scoped_ozon_observation_missing` / `scoped_1688_observation_missing`
  （市场观测需浏览器采集）。
- 为满足 SoD 记录，compliance 身份补真实 scope grant
  （`sge_e53663df…`，owner→risk 评审→admin 记录）。

## 续：风险调整利润仿真（2026-08-02）

新增 `apps/control_plane/risk_adjusted_profit.py`（契约
`kjds-risk-adjusted-profit-simulation-v1`，策略 `2026-08-02.1`）：

- 确定性 Monte Carlo（2000 场景，seed = 策略版本 + 候选指纹）：售价对数正态波动、
  十五项成本在 baseline/downside 之间抽样（evidence-backed 观测项固定不抽样）、
  退货/供应失败/价格战事件抽样。
- 决策效用 = `E[profit] − λ·CVaR_loss − μ·return_risk − ν·supply_risk`
  （λ=1、μ=ν=0.5）；`cvar_loss_cny = max(0, −尾部利润均值)` 为正数形式的
  最差 10% 期望损失，原始尾部均值保留为 `cvar_10_cny` 供审计。
- 发现并修复符号缺陷：初版把负的尾部利润均值直接代入减法，导致
  utility > expected（-424.58 → 39.84）；修复后效用恒 ≤ 期望，
  并新增断言 `utility == expected − cvar_loss − 10.00` 锁定公式。
- `batch_opportunity._economics` 已接入：返回 dict 新增 `"risk_adjusted"`，
  参数取自 market/supply signals（returns_refunds_rate、supply_failure_prob、
  price_war_prob），seed 为 `sale:purchase`。
- 测试：`tests/test_risk_adjusted_profit.py`（3 例）+ `test_batch_opportunity.py`
  候选断言；全量 `1269 passed`；ruff / verify_secrets / diff-check 通过；
  OpenAPI 快照重导幂等（无契约变化）。
- 真实扫描重跑（`POST /v1/batch-market-scans`，operator 身份）：
  `catalog_items=1`、`supplier_observations=1`、`scoped_evidence=1`，
  `status=no_data`、`candidates=0`——真实商品（电力吊机
  `2105343364UB`）与 1688 观测（沙滩罩衫）跨类目匹配不出候选；
  `risk_adjusted` 将在出现精确匹配候选后于真实输出可见（集成由单元测试覆盖）。

## 续：场景化证据等级策略（2026-08-02，按经营架构指引）

经营侧指引：证据层在所有场景必要；“三 Passport”包装按场景分级——
人工小批量用数据库+对象存储保存六项基础证据即可；自动规模化/监管类
要求完整结构化证据；欧盟出口须与 EU DPP 区分并预留对齐缝。

- 新增 `apps/control_plane/evidence_class.py`（契约
  `kjds-evidence-class-policy-v1`，策略 `2026-08-02.1`）：四档
  `manual_small` / `auto_scale` / `regulated` / `eu_export`。
  - 六项基础证据角色（供应商主体、采购链接、商品合格证明、SKU 对照、
    图片来源、基础质检）在所有档位强制；档位差异只在于是否叠加
    三 Passport 与认证要求。
  - `manual_small` 不要求三 Passport，改为六项基础角色门
    （缺失角色名写入 `basic_evidence_incomplete` blocker）；
    发布仍需独立人工确认。
  - `regulated` 强制认证证据；`eu_export` 保留
    `dpp_mapping=dpp-alignment-pending`，明确内部 Passport ≠ EU DPP。
  - 分类完全确定性：显式声明 > 监管类目旗标 > EU 市场 > 自动模式；
    批量扫描默认推断为 `auto_scale`（fail-closed），
    `manual_small` 必须在请求上显式声明
    （`BatchOpportunityPrepareInput.evidence_class`）。
- 批量候选输出新增 `evidence_class` / `passport_required` /
  `basic_evidence_status`；默认自动扫描门禁不变（无安全回归）。
- 测试：`tests/test_evidence_class.py`（10 例）+ `test_batch_opportunity.py`
  集成用例（默认自动档保持 `passport_incomplete`；显式 `manual_small`
  切换到六项基础门）；OpenAPI 快照已重导；
  ADR-0082 记录决策。全量回归与质量门禁见下方状态。

## 续：轻量 SKU 身份卡与验证经济学（2026-08-02，试跑阶段）

经营侧指引：试跑资料与规模化上线治理资料分离——三 Passport 与重型媒体
QA 不是试跑前置条件；先跑通 1688 货源 → Ozon 市场 → 成本利润匹配。

- 新增 `apps/control_plane/sku_identity_card.py`（契约
  `kjds-sku-identity-card-v1`）：17 字段规范身份卡（SKU/类型/额定载重/
  单绳双绳载重/提升高度速度/电压频率功率/钢丝绳/遥控/整机重量/包装尺寸/
  配件/供应商链接/主图）。
  - 核心规格（类型、额定载重、提升高度、电压、频率、功率）两侧必须一致：
    确认冲突直接排除匹配（计入 `spec_mismatch_excluded`），杜绝
    500kg 采购价匹配 1000kg 售价、220V/380V、单绳双绳混配；
    双侧均缺失记为 `unverifiable` 缺口上报，不猜测。
  - 别名表覆盖中英文规格键（额定载重/0.5吨→500kg、1.5kW→1500W 等
    单位归一），指纹 `card_fingerprint` 稳定可审计。
- 验证经济学：新增 `KEY_COST_COMPONENTS`（采购、国内/国际物流、包装、
  平台佣金、支付/FX、税费、退货、损坏损失九项）；试跑档只要求这九项有
  证据，其余组件按政策区间仿真，输出 `landed_cost_interval_cny` /
  `profit_interval_cny` / `estimated_component_names`；
  规模化档保持十五项全证据门不变。
- 六项基础媒体检查（图片与 SKU 一致、图参与文字规格一致、无水印联系
  方式、无品牌 Logo、无夸大宣称、图中配件真实包含）：passed/failed/
  unknown 三态；failed 为任何档位的媒体硬阻断，unknown 只上报缺口；
  重型多模型媒体 QA 推迟到规模化阶段。
- 测试：`tests/test_sku_identity_card.py`（7 例，含单位归一与冲突检测）、
  `test_batch_opportunity.py` 新增核心规格冲突排除与 manual_small 区间
  断言；全量 `1290 passed`；ADR-0083 记录决策。

## 剩余真实输入

1. Canonical Product + 三 Passport + 媒体 QA（真实商品内容/权利证据）。
2. Ozon 与 1688 市场观测浏览器采集（收件箱晋升；1688 观测需重采精确变体）。
3. 完整十五项成本证据（供应商报价/物流/税）→ downside CM3 正 → `pilot_ready`。

## 补充：Canonical Product 与剩余真实输入

- `bind-existing` 确认真实商品 Canonical Product
  `prd_2215304a…`（RU/OZON，`ozon:ozon-primary:2105343364UB`）与 listing 绑定
  已存在（2026-07-25 legacy 创建，绑定 item_hash `8631d985…`）；新 scoped
  catalog item（`d0eea44d…`）已入目录。
- 批量扫描当前：`catalog_items=1`；剩余真实缺口
  `approved_passports_incomplete` / `approved_media_qa_incomplete`
  （Canonical Product 需三 Passport 与媒体 QA）、
  `scoped_ozon_observation_missing` / `scoped_1688_observation_missing`
  （市场观测）、`observation_not_available`。
- 1688 观测载荷：真实 offer（汕头市涵艺服饰，42 CNY，MOQ 2，多色多码），
  但 `variant_key=unselected`——价格随变体可能不同，正确保持
  `variant_selection_unverified`，需浏览器重采精确变体后才能晋升。

# KJDS — AI 跨境电商控制平面

这是面向俄罗斯市场的 AI 跨境电商经营系统。生产数据平台采用 Supabase PostgreSQL，本机 PostgreSQL 保留作开发和离线备用。系统当前覆盖：

- 市场原始观察、来源证据和可复算机会评分；
- Product / Compliance / Quality Passport；
- 图片、视频、文案 Brief，生成资产和五项 QA；
- 带预算封顶与止损线的增长实验；
- 订单费用账本和订单级 CM1 / CM2 / CM3；
- 高风险动作双人审批；
- 受模式和幂等约束的 Agent 任务；
- 稳定的领域事件与外部连接器协议。
- 1688、淘宝、天猫、京东、拼多多、Alibaba、AliExpress、Amazon、Temu、Shopify 和 WooCommerce 的统一供货连接器目录；
- 采购价、国内运费、国际物流、包装、关税、尾程、平台费、广告与退货准备金的单品 CM3 和保本价；
- 通过产品护照、正 CM3 和双人审批门禁生成 Ozon 上架草稿。

整体边界见 [架构说明](docs/architecture.md)，经营执行见 [90 天执行总纲](Ozon_90天执行总纲.md)。

## 当前目录

```text
apps/control_plane/
  api.py              HTTP API
  domain.py           稳定领域实体和状态
  repository.py       测试/开发存储适配器
  services.py         商品、订单、利润、审批、Agent
  intelligence.py     市场数据和机会评分
  content_growth.py   图片/视频/文案与增长实验
  connectors.py       Ozon/广告/物流/结算连接器协议
  ozon_contracts.py   Ozon 订单/费用/退货/结算版本化数据合同
  facts.py            暂存行到不可变正式事实的晋升与血缘
  finance.py          费用字典、FX、三方对账和 13 周现金流
  sourcing.py         全球供货商品、物流利润和上架草稿规则
  source_connectors.py 平台能力目录
  sourcing_store.py   Supabase/PostgreSQL 持久化适配器
  procurement.py      样品采购状态机、供应商实绩与备用方案
  decision_contracts.py 版本化交互模式与不可变决策合同
migrations/
  001_initial.sql     持久化模型与事务事件表
tests/
  test_core.py        核心业务约束测试
```

## Supabase 配置

1. 在 Supabase 新建项目，进入 **Connect**，复制 Session pooler 连接串（端口 5432）。
2. 复制 `.env.example` 为 `.env`。
3. 将连接串协议从 `postgres://` 改为 `postgresql+psycopg://`，并保留 `sslmode=require`。
4. 运行 `uv run python -m alembic upgrade head`。

不要把 `.env`、数据库密码、Ozon API Key 或 service role key 发给 AI，也不要提交到 Git。

## API 身份与紧急停止

- 未配置 `KJDS_API_KEY` 时，所有 `/v1` 请求以失败关闭方式拒绝。
- 前端由 Next.js 服务端代理注入密钥，浏览器不保存 API 密钥。
- 正式双人审批可用 `KJDS_API_KEYS_JSON` 为不同密钥配置独立 actor 和 role；申请人无法批准自己的高风险动作。
- 紧急情况可调用 `/v1/system/kill-switch/engage`；开启后所有普通写操作返回 `423`，只有 `admin` 可解除。

## 不可变证据账本

`/v1/evidence` 接收原始文件并计算 SHA-256，同时记录来源、证据等级、业务生效时间、系统记录时间和创建人。证据可链接到商品、订单、结算或其他证据；PostgreSQL 触发器禁止修改和删除账本行。默认单文件上限为 10 MB，可通过 `KJDS_EVIDENCE_MAX_BYTES` 调整。

已审核的 Product / Compliance / Quality Passport 只能引用账本中存在且哈希复验通过的证据，重复引用会被拒绝。商品放行时系统会重新复验证据，Passport 版本在 PostgreSQL 中只可追加、不可修改或删除。

供应商报价同样必须绑定候选商品、稳定供应商标识并引用哈希复验通过的原始证据；利润场景除报价证据外还必须提供价格、汇率、物流、费率等假设的证据。报价和利润场景在 PostgreSQL 中只可追加；同一平台外部报价编号若提交不同内容会返回冲突，不会覆盖历史。证据血缘会分别连接到 `supplier_offer` 与 `profit_scenario`。

## G0–G1 经营准入状态

`GET /v1/operations/readiness` 按真实数据库事实计算当前阶段门，不接受人工填写“已完成”：三个候选 SKU、三类 Passport、每 SKU 三个不同供应商、正 CM3 场景、Ozon 四类正式事实、费用映射、RUB/CNY 汇率及未知费用都会独立显示。经营负责人和 Ozon 账户证据可以从经营看板直接上传；`POST /v1/operations/gate-evidence` 会自动哈希固化并链接到 `gate_requirement/GOV-001` 或 `gate_requirement/OZN-001`，只有哈希复验通过的证据才计入。前端直接显示每项缺口和下一步，不会把工程骨架冒充为业务放行。

`POST /v1/intake/sku-episodes` 与经营看板的“候选 SKU 一站式录入”会同时建立商品身份、Product / Compliance / Quality Passport 草稿、三份不可变原始证据及血缘。重复提交相同 SKU 与文件会恢复既有对象，不增加虚假版本；同一 SKU 更换商品身份会被拒绝。录入结果始终是待人工审核草稿，不会自动批准合规、采购或上架。

`GET /v1/passport-reviews` 返回当前待审核队列；`POST /v1/products/{product_id}/passports/{kind}/review` 只允许审核角色提交批准、拒绝或阻断结论。审核会创建不可变新版本，使用预期版本防止覆盖并发修改，阻断或拒绝必须填写原因，重复提交同一结论可安全恢复原结果。

`POST /v1/sourcing/comparison-intake` 一次接收同一 SKU 的三家独立供应商报价、三份原始报价文件和一份共同利润假设证据，并为每家生成可比 CM3。`GET /v1/sourcing/comparisons/{product_id}` 返回排序后的报价比较；只有三家证据化供应商、完整利润场景、正 CM3 和三本已批准 Passport 同时满足时，`POST /v1/sourcing/procurement-candidates` 才能建立采购审批。采购申请仍须由不同身份通过双人控制，不会直接下单。

双人批准后的候选可通过 `POST /v1/procurement/sample-orders` 建立受控样品单；确认、发货、签收、验货、黄金样批准/淘汰均通过只可追加的证据事件推进。`GET /v1/procurement/suppliers/performance` 只用实际样品事件计算质量、交付完整度和准时率；备用供应商接口只返回正 CM3 建议，任何切换都会重新创建采购审批，系统不自动付款或替换供应商。

## 交互模式与决策合同

`GET /v1/interaction-profiles` 返回五个固定版本的协作流程：快速解释、苏格拉底澄清、证据研究、决策评审和概率预测；`/eli10`、`/socrates`、`/truth`、`/x10think`、`/oda`、`/product` 只是这些流程的别名，不是绕过经营控制的魔法口令。

`POST /v1/decision-contracts` 会把问题、风险、期限、最大损失、备选方案、假设、未知项和不可变证据编译成只可追加的合同。缺少关键输入时状态为 `clarification_required`，缺少证据时为 `evidence_pending`；高风险合同强制标记人工审批，重大风险保持纯建议。所有合同的 `execution_eligible` 固定为 `false`，模型分析结果必须经过独立的决策、审批与执行链才可能影响真实经营。

## Ozon 数据合同与正式事实

- `GET /v1/contracts/ozon` 返回 `ozon-v1` 订单、费用、退货和结算合同。
- `POST /v1/imports/ozon` 先把原始 CSV/XLSX 固化为 A 级证据，再写入可诊断暂存区；重复文件按 SHA-256 幂等返回。
- `POST /v1/imports/{import_id}/promote` 重新校验合同并晋升为不可变正式事实。缺少源证据或整份被拒绝的导入失败关闭；未知 SKU 保留为 `requires_product_mapping`，不会被静默绑定。
- `GET /v1/facts` 与证据血缘接口可以追溯每条事实的原文件、导入行、记录时间和业务生效时间。

## 财务控制层

- 原始 Ozon 费用码默认进入未知费用队列；只有具备证据、审核人、生效区间和金额符号规则的版本化映射才参与对账。
- FX 按币种对、指定来源和业务日期选择，非本位币金额缺少匹配汇率时失败关闭。
- 财务事实保留原金额、币种、日期、源事实和证据；对账快照分开显示订单应收、已解释调整、平台结算、银行到账、未知费用和差异率。
- 13 周现金流把已承诺项目与概率加权情景分开，不把预测伪装成已经发生的现金事实。

## 本地运行

```powershell
.\scripts\bootstrap.ps1
.\scripts\dev.ps1
```

打开 `http://127.0.0.1:8000/docs` 查看并调用接口。

也可以使用 Docker：

```powershell
docker compose up --build
```

## 测试

通过项目锁定环境执行：

```powershell
uv run ruff check .
uv run python -m pytest
```

完整 G-1 验证（临时 PostgreSQL 迁移回放、API/DB/Web smoke、测试和构建）：

```powershell
.\scripts\verify-g1.ps1
```

实时结果保存在 `.runtime/G1_VERIFICATION.json`。

## 当前成熟度

数据库持久化、Ozon 原文件证据化导入、四类版本化数据合同、正式事实晋升、费用/FX 控制、三方对账、13 周现金流、工具健康检查、多供货平台标准化、物流利润核算和 Ozon 上架草稿已经接通。默认仍为14天影子模式，高风险写操作不会自动执行。真实平台采集需要对应账号/API权限；浏览器登录、验证码和付费授权必须由账号所有者完成。

环境规范见 [TOOLCHAIN.md](TOOLCHAIN.md)，环境决策见 [ADR-0001](docs/adr/ADR-0001-development-environment.md)。

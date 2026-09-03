# 2026-08-14 Ozon Seller API 对账字段学习笔记（公开 API，非经营证据）

| 字段 | 值 |
|---|---|
| doc_id | KJDS-RESEARCH-OZON-API-RECON-001 |
| 状态 | RESEARCH_NOTE / LEARNING_ONLY |
| 生效日 | 2026-08-14 |
| 用途 | 只用于搞清楚「订单 → 平台结算/应计 → 银行到账」的公开 API 口径；不构成真实报价、结算、银行或正式事实 |
| 来源 | [MissiaL/ozon-api](https://github.com/MissiaL/ozon-api) 的 `SKILL.md`、`references/index.md` 与镜像的官方 OpenAPI（`docs.ozon.ru/api/seller/swagger.json`） |
| 红线 | 不含 `Client-Id` / `Api-Key` / 账号 / 银行资料 / PII；不执行写类调用 |

## 0. 先读结论

- 卖家后台 `seller.ozon.ru → Настройки → Seller API` 取 `Client-Id + Api-Key`；只读 key 对写类方法返回 403。
- **没有 sandbox**，`api-seller.ozon.ru` 就是生产店铺；所有可能改店铺/订单/状态的调用必须先由真人批准。
- 绝大多数端点是 `POST`，空参数也要发 `{}`，日期用 RFC3339 带 `Z`（如 `2026-08-14T00:00:00Z`）。
- 官方方法存在 v1–v5 多版本；优先用最高非弃用版本，并读该方法的描述确认继承关系。

## 1. 三表对应的公开 API 口径

| 表 | API 可用性 | 首选端点 | 备注 |
|---|---|---|---|
| A 订单表 | 可用（报告异步） | `POST /v1/report/postings/create` → `POST /v1/report/info` | 对应后台 `FBO → Заказы со склада Ozon`、`FBS → Заказы с моих складов → CSV`；生成后返回 `code`，再用 `report/info` 取 `file` URL 与 `status` |
| B 平台结算/应计表 | 部分可用，注意版本 | 优先 `POST /v1/finance/accrual/postings` + `POST /v1/finance/accrual/by-day` + `POST /v1/finance/accrual/types`；佐证用 `POST /v1/finance/realization/posting` 或 `POST /v2/finance/realization` | `accrual/*` 目前在 `BetaMethod` 组，可能无预告变更；旧的 `/v3/finance/transaction/list`、`/v3/finance/transaction/totals` 已标记 2026-07-06 停用，不能作为当前生产口径 |
| C 银行到账表 | **Seller API 不可替代** | 无 API；只能由真人从收款方（LianLian/PingPong 等）或银行导出对账单 | 跨境店多为 RUB→CNY，到账 T+1~T+3、费率以真实对账单为准，禁止用公开经验外推 |

对账键（沿用 FIN-001）：

`order_id → posting_number → 平台应计/结算记录 → 银行流水备注`

任一层断链即 `UNMATCHED`，禁止估算补齐。

## 2. 订单表：`/v1/report/postings/create`

请求体要点：

- `filter`：可选 `processed_at_from/processed_at_to`、`sku`、`offer_id`、`delivery_schema`、`statuses/status_alias`、`cancel_reason_id`、`warehouse_id`、`title`、`is_express` 等。
- `language`：`DEFAULT`（默认）。
- `with`：可打开 `additional_data`、`analytics_data`、`customer_data`、`jewelry_codes`。

响应：先返回 `{result: {code: string}}`；随后：

- `POST /v1/report/info`，请求 `{code}`，返回 `code / created_at / status / file / error / report_type / params / expires_at`。
- `POST /v1/report/list`，按 `page / page_size / report_type` 列历史报告。

注意：`file` 才是 CSV/XLSX 下载地址。具体 CSV 列名（`posting_number`、`order_id`、`order_date`、`status`、`sku`、`amount` 等）以实际下载文件首行校验为准，不能凭 OpenAPI 推断。

## 3. 平台应计/结算表：优先 `accrual/*`

### 3.1 `POST /v1/finance/accrual/postings`（按 `posting_number` 精确取应计）

请求：

- `posting_numbers`: `string[]`，`minItems=1`、`maxItems=200`。

响应结构（关键字段）：

```text
posting_accruals[]
  posting_number
  accruals[]
    accrual_date          // YYYY-MM-DD
    accrued.amount
    accrued.currency
    quantity
    seller_price.amount
    seller_price.currency
    sku
    type_id               // 用 types 字典翻译成名称
```

### 3.2 `POST /v1/finance/accrual/by-day`（按日期翻页取应计）

请求：

- `date`: `YYYY-MM-DD`，最早 2022-01-01。
- `last_id`: 首页传空字符串；后续传上一次响应里的 `last_id`。

响应结构（关键字段）：

```text
accruals[]
  date
  accrued_category
  item_fees.fees[]
  non_item_fee { type_id, accrued.amount, accrued.currency }
  posting { delivery_schema, delivery_speed, products[] }
  total_amount.amount
  total_amount.currency
  accrual_id
  unit_number
last_id
```

### 3.3 `POST /v1/finance/accrual/types`（应计类型字典）

响应：

```text
accrual_types[]
  id
  name
```

用 `type_id → id` 把 `/v1/finance/accrual/postings` 和 `/v1/finance/accrual/by-day` 中的费用类型翻译成人话，避免把未知 `type_id` 当佣金或当物流费。

### 3.4 实现报告佐证：`/v1/finance/realization/*`

- `POST /v1/finance/realization/posting`：请求 `{month, year}`，返回 `header`（合同/税号/期间等）与 `rows[]`；每行含 `item`、`order.posting_number`、`delivery_commission`、`return_commission`、`commission_ratio`、`seller_price_per_instance`、`row_number`。
- `POST /v2/finance/realization`：请求 `{month, year}`，返回 `result.header + result.rows[]`。
- 范围说明：只含已送达/已退货商品，**不包含取消与未赎回**；早于 2023-08 的期间不可用；哈萨克斯坦 ТОО「ОЗОН Маркетплейс Казахстан」合同卖家不可用。

实现报告适合拿来做「月度平台结算」复核，不适合替代逐笔银行到账。

## 4. 银行到账表：没有 Seller API 替代品

`POST /v1/finance/cash-flow-statement/list` 只返回 Ozon 平台内的财务报告（后台「Финансы → Баланс → Доходы и расходы」），请求 `{date, page, page_size, with_details}`，且只支持 01–15、16–31 两个半月区间；它不是银行/第三方支付的到账流水。

银行到账必须由真人导出：

- 收款方对账单：LianLian / PingPong 等（含 RUB→CNY、到账日期、金额、批次备注）。
- 银行对账单：最终入账账户。
- 用「银行流水备注」里的结算批次号/发送编号与平台 `posting_number` 或结算号回连。

公开资料中「约 1% 费率、T+1~T+3」只是学习参考，不是本项目的已签事实。

## 5. 建议的落地顺序

1. 真人只读导出：订单 CSV（`report/postings/create → report/info`）+ 应计数据（`accrual/by-day` 或 `accrual/postings`）+ 收款方对账单。
2. 用 `accrual/types` 翻译 `type_id`，再用 `posting_number` 关联订单与应计。
3. 银行流水只能由用户提供；API 侧永远不伪造到账。
4. `reconciliation unmatched = 0`、三表同口径、独立复核完成后，才可进入 `CASH_VERIFIED`。

## 6. 未闭合 / 待用户确认

- 尚无真实 `Client-Id / Api-Key` 生产只读调用记录（本笔记只基于公开文档）。
- `accrual/*` 是 Beta 方法，正式进入对账前需用只读 key 实测一次并记录响应哈希。
- 银行/收款方到账原件仍缺，是 `CASH_VERIFIED` 的唯一硬阻塞。

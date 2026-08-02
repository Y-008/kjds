# ADR-0033：利润款到 ERP Item 的受控同步

| 元数据 | 值 |
|---|---|
| status | Accepted for implementation |
| date | 2026-07-27 |
| owner | 经营平台负责人 |
| approver | 用户已授权把已证实利润款写入 ERP 并同步 |
| affects | BR-055 / BR-078 / BR-082 / BR-083 / M0 Truth-Governance |

## 背景

批量机会模块已能形成不可变候选与悲观 CM3，但 ERPNext 目前只有离线投影器。让浏览器或前端直接把“看起来有差价”的商品写入 ERP，会把观察价升级成利润事实，并可能错误创建库存或采购。无忧易售、妙手式的批量操作体验可以借鉴，但 Cookie、内部接口、客户端利润计算和宽权限模式不能复制。

## 决策

新增单一深模块 `ProfitQualifiedErpSync`。调用方只提交授权店铺、冻结 Batch Opportunity run/candidate 与幂等键；模块从 PostgreSQL 权威行重新读取并判定，不接受客户端自报利润。

1. 只有精确身份、完整十五项成本 Evidence、悲观 CM3 大于冻结门槛且守恒为零的候选，才可标记 `profit_qualified` 并生成 ERPNext `Item` 草稿。
2. `Item` 固定 `docstatus=0`、`is_stock_item=1`，初始库存事实为 0；本接口绝不生成采购单、收货、库存调整、付款、广告或 Ozon 写入。
3. KJDS 继续拥有 Product、Evidence、成本与利润真相；ERPNext 只拥有同步后的 Item 草稿。每条请求进入 PostgreSQL outbox，冻结 tenant/store/run/candidate、请求指纹、payload hash、Evidence、状态、尝试次数和回读。
4. 同一作用域和幂等键的精确重试复用；参数或 payload 改变即冲突。跨租户/跨店失败关闭。
5. 连接器使用专用最小权限凭据，只允许 Frappe 官方 REST 的 Item create/read；凭据不入库、不入 Evidence、不回显。未配置连接器时状态为 `blocked_connector_not_configured`，不得声称已同步。
6. 远端写入仅限可逆草稿；写后必须回读 `item_code/docstatus/custom_kjds_product_id` 和响应哈希。回读不一致为 `failed_readback`，保留重试与人工处理，不能继续下游动作。
7. 当前没有 `profit_qualified` 候选时返回真实 `no_data`，创建零 outbox、零 ERP 单据。

## 深模块接口

- `prepare(run_id, candidate_id, store_ref, idempotency_key)`：权威复验并建立草稿/outbox，或给出阻断、Owner、SLA 与下一动作。
- `dispatch(sync_id)`：仅当连接器已配置且状态允许时执行一次 Item upsert/create；不扩展到其他 DocType。
- `get/list`：返回状态、哈希、Evidence 与回读，不返回凭据。

## 未选择方案

- 不把全部候选批量推入 ERP 后再人工筛：会污染商品主数据并掩盖利润缺口。
- 不让前端拼 ERP payload 或计算 CM3：会形成第二规则实现。
- 不用 ERP Item 库存代表“供应商有货”：供应可购性与实际库存是不同事实。
- 不在本切片安装 ERPNext 或生成采购单：当前没有已证实利润款，且交易 Owner 晋升、备份恢复和卸载演练尚未通过。

## 验收

- 零利润款时零写入；坏 Evidence、非正悲观 CM3、成本不完整、非零守恒、跨店全部拒绝。
- 精确重试幂等、变更冲突；连接器缺失可解释阻断。
- 模拟 ERPNext 只收到 Item 草稿，回读一致才成功；任何路径都不创建采购/库存/付款/Ozon 写入。
- 匿名 401、越权 403；OpenAPI、PostgreSQL 迁移回放、全量测试和容器健康通过。

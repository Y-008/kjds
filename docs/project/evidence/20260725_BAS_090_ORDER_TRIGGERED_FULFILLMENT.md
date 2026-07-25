# BAS-090 销售单触发采购与跨境巴士动态选仓工程证据

## 结论

KJDS 已实现 BR-067 的内部受控履约账，明确区分：

- Ozon 商品卡/Listing：上线售卖，不创建采购；
- Ozon 销售订单：买家真实出单，触发唯一履约需求；
- 供应商采购订单：动态选仓、完整正 CM3 和独立审批后，才允许记录人工确认结果。

实现不调用 1688 下单、支付、跨境巴士预报或物流写接口。

## 工程交付

- `apps/control_plane/sales_fulfillment.py`
  - 无地址初始需求；
  - 跨境巴士路线快照和地址有效时间；
  - `GOOL -> GUOO` 规范化；
  - UNI 新连接失败关闭，既有连接只允许 `legacy_only`；
  - 三份当前报价、完整正 CM3、三类 Passport 和独立采购审批复验；
  - 供应商订单收货仓逐字段一致性；
  - 国内发货、仓库签收、打包贴标和国际交接顺序账。
- `migrations/versions/20260725_0041_order_triggered_fulfillment.py`
  - 唯一销售单履约需求；
  - 不可变事件序列、Evidence 外键、RLS 和数值约束。
- `/v1/fulfillment/plans`
  - 建立、查询、选路线、申请采购审批和记录后续事件。
- Web
  - 自有竞品能力导航；
  - Listing → 销售单 → 采购单三单说明；
  - 订单履约状态、国内仓未知状态、路线和下一动作。
- `docs/adr/ADR-0019-order-triggered-procurement-and-routing.md`
  - 固化三单边界、延迟选仓和不自动执行决策。

## 验证

- `uv run python scripts/verify_secrets.py`：456 个非忽略工作区文件及 451 个历史路径通过。
- `uv run ruff check .`：通过。
- `uv run pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-local`：377 passed。
- `npm test`：26 passed。
- `npm run build`：Next.js 生产构建通过。
- `uv run alembic heads`：单一 head `20260725_0041`。
- 从空 PostgreSQL 17 数据库执行 `uv run alembic upgrade head`：完整回放通过。
- PostgreSQL 检查确认 `sales_fulfillment_plans` 和 `sales_fulfillment_events` 存在。
- Docker API `/health/ready`：`status=ok`、`database.status=ok`。
- `git diff --check`：通过。

## 未完成的真实业务输入

- 尚无 KJDS 已记录的真实 Ozon 买家销售订单，因此没有创建履约需求。
- 尚未对真实订单读取跨境巴士账户内可选路线和国内仓地址。
- 尚未发出三家询价、取得书面报价、创建 1688 采购单或支付。
- 以上外部动作仍分别需要真实数据、精确审批和职责分离，不由本工程交付自动完成。

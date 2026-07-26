# BAS-098 Supplier RFQ Dispatch Proof

- 日期：2026-07-26
- 需求：`BR-073`
- 架构决策：`ADR-0024`
- 验收对象：`SupplierRfqDispatchWorkspace`
- 结论：代码闭环通过；真实业务事实仍保持在“询价包已冻结、尚未发送”的正确状态

## 1. 本次实现

`SupplierRfqDispatchWorkspace` 统一负责以下不变量：

1. 读取并复验不可变 RFQ Evidence；
2. 要求前端提交与冻结 RFQ 逐字一致的完整正文；
3. 固化供应商标识、平台、稳定定位、会话编号、带时区发送时间和原始截图/导出哈希；
4. 以幂等来源引用写入 Grade B 发送证明；
5. 由不同身份完成四项核验并写入 Grade A 复核凭证；
6. 保持 `delivery_confirmed`、`supplier_replied`、`counts_as_supplier_quote` 和所有自动外部动作均为 `false`；
7. 供应商回复如引用发送证明，必须匹配同一 Product、RFQ、供应商标识和平台，并建立 `supplier_response_to_dispatch` 血缘。

通用 Evidence 上传和通用 Lineage 接口均保留了专用来源、角色和关系，不能绕过专用工作流伪造发送或复核。

## 2. 真实数据回放

当前真实 RFQ：

- 店铺：`ozon-primary`
- Ozon Offer：`2105343364UB`
- Marketplace SKU：`2216781923`
- Product：`prd_2215304aca03f42ab0921102a2d58de9`
- RFQ Evidence：`evd_ad50f959c4904a05852b0551f34761f3`
- RFQ package hash：`2340cf1342efd687c3bc47abc75d3a487b1ab0db6f3165000d8dcb043ab40ca4`

重建 Docker Compose 后：

- API、Web、PostgreSQL 均为 healthy；
- `/health/ready` 返回 HTTP 200、`status=ok`、数据库 `status=ok`；
- Alembic `current` 与 `heads` 均为 `20260726_0050`；
- PostgreSQL 已存在局部唯一索引 `uq_supplier_rfq_dispatch_source_ref`；
- `GET /v1/sourcing/rfq-packages` 返回上述 1 个真实 RFQ；
- `GET /v1/sourcing/rfq-dispatches` 返回 `[]`；
- `GET /v1/sourcing/quote-evidence` 返回 `[]`；
- `GET /v1/sourcing/offers` 返回 `[]`。

本次没有联系任何 1688/Alibaba 供应商，没有上传伪造截图，没有创建报价、采购、付款或 Ozon 写入。

## 3. 负向安全验收

使用真实 RFQ Evidence 执行两个必须失败且不得落库的请求：

1. 提交篡改后的 `sent_message_text`：
   - HTTP 422；
   - `Supplier RFQ dispatch message differs from the frozen RFQ`。
2. 通过通用 Evidence API 伪造 `supplier_rfq_dispatch`：
   - HTTP 422；
   - `Reserved evidence source requires its dedicated workflow`。

随后再次读取 `GET /v1/sourcing/rfq-dispatches`，HTTP 200 且数量仍为 0。

## 4. 浏览器验收

Playwright 在 `http://127.0.0.1:3000/#sourcing` 验证：

- 标题为“询价包 → 发送证明 → 回复归因 → 报价复核 → 三家 CM3”；
- 计数为“1 个询价包 · 0 个已核验发送 · 0 份已接受报价”；
- 当前真实 RFQ、Evidence ID 和 package hash 正确展示；
- 发送登记要求供应商身份、平台、稳定定位、会话编号、实际时间、幂等编号和平台原始文件；
- 页面明确提示只有实际发送后才能上传，按钮本身不会联系供应商；
- 回复表单只有已独立核验的发送证明可供选择；
- 最终化按钮在三份已接受报价不足时保持禁用；
- 点击“复制询价文案”后提示“复制不代表已发送或已取得报价”；
- 浏览器控制台错误数为 0。

本地视觉验收截图：

`output/playwright/bas-098-supplier-rfq-dispatch-workspace.png`

## 5. 自动化验证

- 密钥扫描：510 个非忽略工作树文件及 507 个历史路径通过；
- 全量 Ruff：通过；
- 全量后端测试：482 passed；
- `npm ci`：0 vulnerabilities；
- 前端契约测试：35 passed；
- 前端生产构建和 TypeScript：通过；
- `git diff --check`：通过；
- 从全新空 PostgreSQL 数据库执行 `alembic upgrade head`：通过；
- 新库 `alembic current` 为 `20260726_0050 (head)`，发送证明唯一索引存在；
- 临时验收数据库已删除，无遗留 `kjds_dispatch_smoke_%` 数据库。

GitHub CI 在 PR 创建后继续验证。

## 6. Findings

- `P1 / auto-fix`：交付审阅发现完全相同的报价 Evidence 重放时可能尝试改绑另一条发送证明。报价权威服务现会对复用记录的完整不可变 RFQ/dispatch 上下文做冲突校验，并有回归测试证明旧记录和原血缘不会被重新归因。
- `P0/P1/P2`：无未处理发现。
- `Info / no-op`：当前没有真实供应商发送证明，因此系统正确保持 0 发送、0 回复、0 报价。只有取得可回查的真实平台截图或会话导出后，才允许推进第一条正向业务记录。

# 剩余任务与并行调度

| 元数据 | 值 |
|---|---|
| doc_id | KJDS-PLAN-001 |
| owner | 项目负责人（待确认） |
| approver | 经营负责人 |
| status | Active |
| version | 1.0 |
| last_reviewed | 2026-07-16 |
| next_review | 2026-07-23 |
| gate | G-1–G1 |

任务工作簿中 108 项任务、58 项 P0 继续作为候选库存；当前执行 P0 收敛为以下 13 项。没有进入本表的任务不得占用当前开发窗口。

## 当前 P0

| ID | Gate | 任务 | Owner | 验收 | 依赖 | 状态 |
|---|---|---|---|---|---|---|
| BAS-001 | G-1 | 审阅并分层冻结当前工作区 | 工程负责人 | 可回滚提交；无不明来源改动 | 无 | NOT_STARTED |
| BAS-002 | G-1 | PostgreSQL 迁移与回滚验证 | 工程负责人 | 迁移到 0003；upgrade/downgrade 证据 | BAS-001 | NOT_STARTED |
| BAS-003 | G-1 | API、DB、Web 真实 smoke | 工程负责人 | 冷启动可复现；健康检查通过 | BAS-002 | NOT_STARTED |
| BAS-004 | G-1 | 环境状态自动生成 | 工程负责人 | 不再依赖过时静态 PASS 文档 | BAS-003 | NOT_STARTED |
| SEC-001 | G-1 | API 身份认证 | 工程负责人 | `KJDS_API_KEY` 或正式身份层生效；未授权为 401/403 | BAS-003 | NOT_STARTED |
| SEC-002 | G0 | 审批身份、Kill Switch 与审计 | 工程+经营 | 申请/批准不可伪造；紧急停止可验证 | SEC-001 | NOT_STARTED |
| SKU-001 | G0 | 确认三个真实候选 SKU | 商品负责人 | 每个 SKU 有稳定 ID、来源和红线结论 | Owner/RACI | BLOCKED |
| SKU-002 | G1 | 三类 Passport 与证据包 | 商品/合规 | 3×3 Passport 完整且人工批准 | SKU-001 | BLOCKED |
| SKU-003 | G1 | 报价、样品、包装和物流实测 | 商品/供应链 | 每 SKU 三报价；重量尺寸与包装有实测 | SKU-001 | BLOCKED |
| OZN-001 | G0 | Ozon 账户、权限和收款路径核验 | 经营负责人 | 官方后台/合同/权限证据 | 人工登录 | BLOCKED |
| OZN-002 | G1 | Ozon 数据合同与只读接入矩阵 | 工程+经营 | 订单/费用/退货/结算字段与来源明确 | OZN-001 | NOT_STARTED |
| FIN-001 | G1 | 费用字典、FX 与 CM3 口径 | 财务负责人 | 金额/币种/日期/证据齐全；未知费用隔离 | OZN-002 | NOT_STARTED |
| EVD-001 | G1 | 不可变证据对象与双时间设计 | 工程负责人 | 哈希、原件、血缘、等级、effective/recorded 时间可验证 | BAS-002 | NOT_STARTED |

`BLOCKED` 项不是工程问题：需要账号所有者、真实商品/供应商、样品或一手业务文件。增加开发窗口不能消除这些阻塞。

## 第一批四窗口：只冻结合同与模板

| 窗口 | 文件所有权 | 输入 | 输出 | 验收 | 禁止事项 |
|---|---|---|---|---|---|
| A 治理 | `docs/project/00–04` | 方案母稿、Backlog、负责人决定 | 章程、Gate、RACI、未知项 | 所有当前任务有 Gate/Owner/验收 | 不改业务代码/迁移 |
| B SKU 准入 | `docs/project/templates/T03*` + SKU 资料区 | 三个真实 SKU、报价、样品、合规资料 | 三 Passport 和 Episode 包 | 3/3 字段完整，缺失项明确 UNKNOWN | 不猜硬事实 |
| C 财务 | `docs/project/templates/T04*` + 财务资料区 | Ozon 费用、结算、银行、FX | 费用字典、三方对账、现金模板 | 数字可复算、差异可隔离 | 不用浮点/“其他”吞差异 |
| D 工程合同 | ADR、数据合同、连接器矩阵 | 当前代码、官方 API/报表 | 证据层/Ozon/安全实现合同 | 能直接生成测试与迁移验收 | 不同时修改 `api.py` 和共享迁移 |

并行原则：每个窗口拥有独立文件区；`api.py`、共享领域对象和 Alembic 迁移由单一集成人合并。多个窗口不得同时修改同一文档或 Schema。

## 第二批代码开发（模板冻结后）

1. 不可变证据对象、血缘和双时间。
2. Ozon 暂存行到正式订单/费用/退货/结算事实的转换。
3. 财务账本、三方对账、差异队列和 13 周现金流。
4. API 身份、可信审批、原子 outbox、Command/Result/Readback/Kill Switch。
5. 里程碑、准入和异常经营看板。

## 每日调度规则

- 每个窗口每天最多一个 `IN_PROGRESS` 主任务。
- 开始前填写任务合同；结束时给出证据、状态和下一个阻塞。
- 发现跨窗口 Schema 变更时暂停实现，先提交 ADR/数据合同。
- 每日整合只做交叉引用、冲突消解和验收检查，不追加新愿景。
- 每周从 P0 删除不再提高当前 Gate 通过率的任务。


# BAS-076：实际成本权威证明与执行前复验

## 结论

利润场景中的 `actual` 不再接受调用方自报。系统复用既有 Evidence、Blob 和 Lineage，为 15 个命名成本项建立精确的实际权威类型和独立复核证明；没有新增数据表、服务依赖、成本总账或自动入账。

状态：`DONE_ENGINEERING`。本次证明的是控制能力，不代表当前三个真实 SKU 已取得全套实际账单，也不把估算 CM3 冒充到账利润。

## 失败关闭规则

1. 每项 `actual` 必须引用当前完整性通过的原件，并由不同于上传者的 Reviewer、Compliance 或 Admin 复核。
2. 接受结论必须同时确认原件真实性、成本范围、计费/责任主体、金额—币种—期间；缺一项即不可接受。
3. 权威类型按成本项固定，例如采购成本只接受供应商发票/付款证明，平台费只接受 Ozon 交易结算，官方规则、公开报价和第三方计算器只能作 `estimate`。
4. 证明绑定原件 SHA-256、成本项、权威类型、上传者和复核者；同一复核者不能覆盖原结论，任一有效拒绝优先阻断。
5. 利润场景创建、组合 readiness、采购评审、样品订单与 Listing 草稿在动作时重算原件完整性和 `actual` 证明，不沿用陈旧放行状态。

## 实现边界

- `apps/control_plane/cost_evidence_review.py`：实际成本权威证明、不可变复核和失败关闭状态。
- `apps/control_plane/sourcing.py`：场景创建及 release-time 复验唯一入口。
- `apps/control_plane/procurement.py`、`readiness.py` 与 API：复用同一入口，不复制判断。
- `docs/project/registries/cost_authority_sources.json`：机器可读的 15 项成本—权威类型映射，并由测试防漂移。
- 新 API：`GET/POST /v1/finance/cost-evidence/{evidence_id}/authority-review`。

## 验证

- 目标域测试：29/29 通过；
- API/OpenAPI 合同：8/8 通过；
- Python 全量回归：315/315 通过（仓库内隔离 pytest 临时目录；系统默认临时目录因 Windows 权限失败，代码测试无失败）；
- Ruff：通过；
- G-1 端到端门禁：`PASS`（`2026-07-20T06:03:53.9770281Z`–`2026-07-20T06:06:20.910838Z`）；
- G-1 实际验证待复核→自审 422→独立接受→`actual` 场景创建，`actual_cost_authority_gate=true`；
- G-1 同时验证 315 项 Python、16 项 Web、Web build、PostgreSQL `20260720_0038`、API/Web 容器、备份恢复和全部清理；恢复包 SHA-256：`55255e66790fd6ff112b8f10733c858c2f794d18d580544ac77a16e9264604e3`。

## Review

- P0：未发现。
- P1 / ask-user：真实 `actual` 仍需对应 SKU 的供应商发票/付款、物流终账、Ozon 结算/广告/退货报表、税关凭证和真实换汇记录，并由独立身份逐项接受。
- P1 / defer：未取得首份真实格式前，不开发 15 套专用解析器；先走通人工存证与复核，再对重复量最大的格式做只读适配。
- P2 / no-op：不安装完整 ERP 来“证明”实际成本；ERP 只能接收经批准的投影，不能替代 KJDS 的原件、权威证明和责任链。

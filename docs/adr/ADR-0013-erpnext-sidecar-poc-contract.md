# ADR-0013：ERPNext 隔离侧车 PoC 合同

| 元数据 | 值 |
|---|---|
| status | Accepted for contract-only PoC |
| date | 2026-07-20 |
| owner | 工程负责人 |
| approver | 经营负责人待 G0 复核 |
| affects | BR-055 / G-1 / ERPNext 隔离准入 |

## 背景

KJDS 已选择 ERPNext 作为确定性采购、库存和会计单据的首选隔离 PoC，但“能够调用 REST API”并不证明可以安全成为业务事实所有者。若在外部 ID、幂等、证据、金额、币种和 Owner 未冻结前安装 ERP，会制造第二套可写库存与财务事实。

## 决策

1. 第一阶段只实现合同与离线投影，不启动 ERPNext、不连接生产账户、不保存 ERP 凭证。
2. 所有投影固定为 `poc_dry_run`、ERPNext `docstatus=0`、`automatic_submit=false`；本阶段不存在远程写方法。
3. 每个投影必须包含稳定来源对象、正整数来源版本、目标 DocType、稳定外部 ID、稳定幂等键、规范化 payload SHA-256、至少一份 Evidence ID 和明确 Owner。
4. 同一批次出现相同幂等键但 payload 哈希不同必须失败关闭；精确重试允许复用。
5. 金额只接受十进制字符串，币种只接受三位 ASCII 大写。跨币种单据必须同时提供交易币种、公司币种、正汇率、带时区生效时间和汇率 Evidence；不得用浮点或当前汇率补值。
6. KJDS 在 PoC 阶段继续拥有 Canonical Product、Evidence、CM3、决策、审批和审计；ERPNext 只被评估为 Item 投影、采购单、收货、到岸成本、销售/退货、总账和付款单据的候选 Owner。
7. Webhook 验证使用 Frappe 文档约定的 HMAC-SHA256；缺失密钥、签名格式错误或不匹配一律拒绝。
8. 对账输出只能是 `matched`、`difference` 或 `blocked`，保存原币金额、容差和差额；不得自动过账、自动修正或把差额塞入“其他”。

## 未选择方案

- 不先安装官方/社区 Docker 栈：运行成功不能验证业务所有权、金额和对账合同。
- 不把 ERPNext 客户端塞进通用 `JsonHttpProvider`：PoC 尚无远程写权限，过早暴露写方法会扩大误用面。
- 不新增同步表或迁移：在真实样本和远程 PoC 前，现有不可变 Evidence 与离线合同足够验证设计。
- 不同时 PoC Odoo、Dolibarr：只有 ERPNext 违反硬约束时才评估第二候选。

## 验收

- Item、Purchase Order 和 Settlement/Journal 候选投影具有稳定 ID、版本、幂等键与证据。
- 浮点金额、非法币种、无证据、无时区汇率、生产写模式和自动提交全部被拒绝。
- 精确重复投影可重试；同键不同 payload 被拒绝。
- HMAC-SHA256 正确签名通过，错误签名拒绝。
- 同币种对账能区分匹配与差额；币种不一致时阻塞。
- `uv run ruff check .`、相关测试、完整回归和 `git diff --check` 通过。

## 晋升条件

只有上述合同通过后，才允许单独评审 ERPNext 容器与最小权限用户。远程 PoC 仍只能使用脱敏测试公司和草稿单据；Owner 迁移、真实库存、会计过账、付款或 Ozon 写权限需要新的 ADR、双人批准、备份恢复和卸载演练。

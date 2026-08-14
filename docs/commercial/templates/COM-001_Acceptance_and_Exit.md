# COM-001 验收、数据返还与退出模板

| 字段 | 值 |
|---|---|
| template_id | `COM-001-ACCEPTANCE-EXIT-v1` |
| customer_ref | `[CUSTOMER_REF]` |
| deployment_ref | `[DEPLOYMENT_REF]` |
| tenant/entity/store | `[TENANT_REF] / [ENTITY_REF] / [STORE_REF]` |
| service | `[five_day_diagnosis / ninety_day_design_partner]` |
| evidence_pack_version | `[VERSION]` |

本模板由服务交付 Owner 填写、客户运营与财务角色分别复核、Independent Verifier 终验。
只记录脱敏引用、计数、哈希、命令和状态，不记录凭据、原始客户正文、银行信息或 PII。

## 1. 交付验收

| 检查 | 预期 | 实际 | Evidence/Artifact ref | 状态 |
|---|---|---|---|---|
| 精确作用域 | 单客户、单店、约定期间、最多 3 用户 | `[VALUE]` | `[REF]` | `[PASS/FAIL]` |
| 活跃 SKU | 50–500，计数口径一致 | `[VALUE]` | `[REF]` | `[PASS/FAIL]` |
| 数据地图 | 来源、期间、哈希、覆盖和隔离项完整 | `[VALUE]` | `[REF]` | `[PASS/FAIL]` |
| 币种 | 100% 金额带币种 | `[VALUE]` | `[REF]` | `[PASS/FAIL]` |
| FX | 来源、日期、公式和舍入可复算 | `[VALUE]` | `[REF]` | `[PASS/FAIL]` |
| downside CM3 | 目标 ≥80% 活跃 SKU 可解释 | `[VALUE]` | `[REF]` | `[PASS/BLOCKED]` |
| 结算映射 | 目标 ≥90% 已分配或明确 `unallocated` | `[VALUE]` | `[REF]` | `[PASS/BLOCKED]` |
| 首次可信价值 | T0 后 ≤5 工作日且四项条件齐全 | `[VALUE]` | `[REF]` | `[PASS/BLOCKED]` |
| 实施工时 | 目标 ≤12 人时 | `[VALUE]` | `[REF]` | `[PASS/BLOCKED]` |
| 外部写 | 计数严格为 0 | `[VALUE]` | `[REF]` | `[PASS/FAIL]` |
| 跨客户/跨店 | 双向负向测试零数据 | `[VALUE]` | `[REF]` | `[PASS/FAIL]` |
| 恢复/回滚 | 当前 Release 可恢复、可回滚 | `[VALUE]` | `[REF]` | `[PASS/FAIL]` |

### 客户决定

- 运营角色：`[accepted / defects_attached / review_pending]`
- 财务角色：`[accepted / defects_attached / review_pending]`
- 首次可信价值：`[passed / blocked]`
- 决定：`[continue / pause / stop / renew / exit]`
- 结构化缺陷或阻断：`[REFERENCES_ONLY]`
- 下一复核日期：`[DATE]`

## 2. 退出触发

- 约定期限届满。
- 双方签署提前结束或不续约决定。
- 精确作用域、授权或客户输入持续失效。
- 出现跨客户/跨店访问、未授权外部写或重大数据完整性事件。
- 双方确认进入替代方案或完成全部目标。

退出决定必须冻结最后服务状态、Release、迁移 head、数据窗口、未关闭事项、退款/服务信用
状态和 Evidence 包版本。

## 3. 数据导出包

服务方在退出决定后 5 个工作日内生成约定导出包：

| 组成 | 内容 |
|---|---|
| manifest | customer/deployment/scope hash、生成时间、版本、文件清单 |
| canonical export | 约定商品、费用、结算、到账映射和决策数据 |
| evidence index | Evidence ID、来源等级、时间、内容哈希和血缘引用 |
| audit export | 用户、作用域、读取、验收、事故和商业事件摘要 |
| exception list | `no_data`、`unallocated`、未关闭缺陷和 Owner |
| integrity | 每文件大小和 SHA-256；总包 SHA-256 |

导出前后均执行精确作用域复验。客户运营和财务角色在收到后 5 个工作日内分别确认完整性
或提交结构化缺陷。任一角色未响应时，服务方在第 6 个工作日同时升级至两个客户角色、
服务交付 Owner 和 Independent Verifier，并提供最后 5 个工作日复核窗。

最后复核窗结束仍无双角色结论时，Independent Verifier 在 2 个工作日内复验 manifest、
作用域、文件计数、SHA-256、缺陷记录和下载可用性：

- 复验通过，状态记为 `customer_silent_verified`，仅授权退出时钟继续，不代表客户商业
  验收、价值确认、付款豁免或案例授权。
- 复验失败，状态记为 `exit_verification_failed`，服务交付 Owner 在 2 个工作日内修复并
  重新发起独立复验。

从退出决定到主数据删除最长为 30 个自然日；客户沉默不延长该上限。

## 4. 返还、保留与删除

1. 客户双角色确认导出完整，或 Independent Verifier 形成 `customer_silent_verified` 后，
   访问状态转为 `read_only`，再转为 `closed`。
2. 主应用和数据库中的客户经营数据在上述结论后 10 个工作日内删除，且最迟不超过退出
   决定后 30 个自然日。
3. 关闭后不再生成该客户的新备份；既有加密备份按 14 天滚动保留自然到期，且不进入日常
   恢复源。最终备份到期最迟不超过退出决定后 44 个自然日。
4. 凭据、会话、证书绑定和用户访问同时撤销，并执行回读。
5. 合同、发票、退款、争议及法定留存记录与客户经营数据分离，按适用法定期限保存。任何
   法定保留例外必须记录法律依据、批准角色、数据类别、最小范围、隔离位置、到期日、
   复核日和最终删除触发；该数据不得恢复到日常服务或 Agent 学习环境。
6. 可保留非可逆的文件哈希、删除证明和审计引用；不保留可重建客户经营事实的载荷。

## 5. 删除与关闭终验

| 验证 | 命令/方法 | 输入 | 原始输出引用 | Exit status | Verifier |
|---|---|---|---|---:|---|
| 应用访问关闭 | `[COMMAND]` | `[SCOPE]` | `[REF]` | `[CODE]` | `[ROLE]` |
| 数据库作用域零行 | `[COMMAND]` | `[SCOPE]` | `[REF]` | `[CODE]` | `[ROLE]` |
| 凭据/会话撤销回读 | `[COMMAND]` | `[SCOPE]` | `[REF]` | `[CODE]` | `[ROLE]` |
| 备份清单与到期日 | `[COMMAND]` | `[SCOPE]` | `[REF]` | `[CODE]` | `[ROLE]` |
| 跨客户负向复验 | `[COMMAND]` | `[SCOPE]` | `[REF]` | `[CODE]` | `[ROLE]` |
| 导出包完整性 | `[COMMAND]` | `[MANIFEST]` | `[REF]` | `[CODE]` | `[ROLE]` |

任一检查失败时，状态保持 `exit_verification_failed`，保留最小 Evidence，并由独立 Owner
登记修复动作、期限和复验记录。

若法定保留例外存在，技术关闭仍须在退出决定后 44 个自然日内完成；关闭证明同时列出
已删除数据、例外数据、隔离控制、批准人和到期删除日期。Independent Verifier 每 30 个
自然日复核未到期例外，到期后 2 个工作日内验证最终删除。

## 6. 签署

| 角色 | 决定 | 姓名/职务 | 签署 | 日期 |
|---|---|---|---|---|
| 服务交付 Owner | `[complete / blocked]` | `[NAME_AND_ROLE]` | `[SIGNATURE]` | `[DATE]` |
| Independent Verifier | `[passed / failed]` | `[NAME_AND_ROLE]` | `[SIGNATURE]` | `[DATE]` |
| 客户运营验收角色 | `[accepted / defects]` | `[NAME_AND_ROLE]` | `[SIGNATURE]` | `[DATE]` |
| 客户财务验收角色 | `[accepted / defects]` | `[NAME_AND_ROLE]` | `[SIGNATURE]` | `[DATE]` |

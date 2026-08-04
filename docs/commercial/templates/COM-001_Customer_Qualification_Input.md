# COM-001 客户资格与输入模板

| 字段 | 值 |
|---|---|
| template_id | `COM-001-CUSTOMER-QUALIFICATION-INPUT-v1` |
| status | `internal_review_only` |
| permitted_repository_content | 匿名稳定引用、角色、状态、计数和 SHA-256 |
| prohibited_repository_content | 真名、联系方式、地址、凭据、银行资料、买家 PII、原始经营正文 |

本模板执行
[ICP 资格与拒绝清单](../COM-001_ICP_Qualification_and_Reject_List.md)，
为[五工作日诊断 SOW](COM-001_5_Day_Diagnostic_SOW.md)提供输入准入结论。填写真实客户
资料时，应在批准的客户环境保存原件；仓库版本只记录脱敏引用和 Evidence ID。

## 1. 客户与单店范围

| 检查 | 输入 | 规则 | 状态 |
|---|---|---|---|
| customer_ref | `[ANONYMOUS_STABLE_REF]` | 必填；不使用客户真名 | `[ready/missing]` |
| 客户主体 | `[ENTITY_REF]` | 本服务只覆盖 1 个主体 | `[ready/missing]` |
| 当前 Ozon 店数 | `[1–3]` | ICP 为 1–3 店 | `[qualified/reject]` |
| 本次店铺 | `[STORE_REF]` | 只覆盖其中 1 家 Ozon 店 | `[ready/missing]` |
| 活跃 SKU | `[COUNT_50_TO_500]` | 50–500 | `[qualified/reject]` |
| 访问用户 | `[COUNT_1_TO_3]` | 最多 3 个实名用户 | `[qualified/reject]` |
| 运营验收角色 | `[ROLE_REF]` | 必须与财务角色分别确认 | `[ready/missing]` |
| 财务验收角色 | `[ROLE_REF]` | 必须与运营角色分别确认 | `[ready/missing]` |
| 合法收款路径 | `[EVIDENCE_REF]` | 只记录复核引用 | `[ready/unknown]` |

资格模板只收角色引用，不在仓库保存用户姓名、手机号、邮箱、账号或证件。

## 2. 业务问题与成功条件

- 当前最重要的问题：`[profit / return / settlement / cash / data_quality / other_typed_slot]`
- 当前使用流程：`[ERP / spreadsheet / manual / mixed]`
- 当前对账工时基线：`[MEASUREMENT_REF / UNKNOWN]`
- 客户期望确认的事实：`[FACT_QUESTION_REF]`
- 最小成功条件：`[CUSTOMER_ACCEPTED_PROBLEM_AND_NEXT_ACTION]`
- 必须停止的条件：`[STOP_CONDITION_REF]`
- 案例授权：默认 `false`；另行书面选择后才变更

## 3. 数据范围与期间

诊断窗口至少连续 28 个自然日。每项输入必须包含来源、期间、时区、币种、作用域、文件或
响应 SHA-256、提供角色和当前复核状态；缺失项填写 `UNKNOWN/no_data`。

| 数据域 | 必要性 | source/evidence ref | 期间 | 完整度 | 缺失处理 |
|---|---|---|---|---|---|
| 商品目录与活跃 SKU | T0 必需 | `[REF]` | `[WINDOW]` | `[ready/missing]` | 缺失则 `input_not_ready` |
| 官方订单或财务明细 | T0 至少一类 | `[REF]` | `[WINDOW]` | `[ready/missing]` | 两类都缺失则 `input_not_ready` |
| 至少 1 个 SKU 正式成本 | T0 必需 | `[REF]` | `[AS_OF]` | `[ready/missing]` | 缺失则 `input_not_ready` |
| 取消/退货/退款 | 价值输入 | `[REF/UNKNOWN]` | `[WINDOW]` | `[ready/no_data]` | 利润结论标记缺口 |
| 平台费用/计提 | 价值输入 | `[REF/UNKNOWN]` | `[WINDOW]` | `[ready/no_data]` | settlement/cash 保持受限 |
| 平台结算 | 价值输入 | `[REF/UNKNOWN]` | `[WINDOW]` | `[ready/no_data]` | 未映射项进入 `unallocated` |
| 银行到账 | Actual Cash 必需 | `[REF/UNKNOWN]` | `[WINDOW]` | `[ready/no_data]` | Actual Cash Profit=`no_data` |
| FX 来源与日期 | 跨币种必需 | `[REF/UNKNOWN]` | `[AS_OF]` | `[ready/no_data]` | 禁止跨币种合计 |
| 采购/物流/包装/仓储 | downside 输入 | `[REF/UNKNOWN]` | `[AS_OF]` | `[ready/partial/no_data]` | 逐项标记 UNKNOWN |
| 费用字典与人工绑定 | 分配输入 | `[REF/UNKNOWN]` | `[AS_OF]` | `[ready/partial/no_data]` | 无绑定项保持 `unallocated` |

## 4. 只读授权准入

| 检查 | 输入 | 通过条件 | 状态 |
|---|---|---|---|
| 授权方式 | `[official_export / scoped_read_api]` | 官方导出或最小权限只读接口 | `[ready/reject]` |
| 授权主体 | `[AUTHORITY_EVIDENCE_REF]` | 与客户主体/店铺一致 | `[ready/missing]` |
| capability | `[catalog.read / finance.read / other_read]` | 仅约定读取能力 | `[ready/reject]` |
| 有效期 | `[VALID_FROM / EXPIRES_AT]` | 覆盖交付窗口且可撤销 | `[ready/missing]` |
| 撤销方式 | `[REVOCATION_REF]` | 客户可执行并可回读 | `[ready/missing]` |
| credential storage | `[SECRET_MANAGER_REF]` | 凭据不进入 Git、对话或 Agent | `[ready/reject]` |
| 外部写 | `0` | 所有第三方业务写关闭 | `[ready/reject]` |
| 跨客户/跨店 | `0` | 负向检查零数据 | `[ready/reject]` |

本模板不填写 API Key、Cookie、验证码、密码、银行账号或原始授权正文。

## 5. 立即拒绝条件

任一项成立时，资格结论为 `rejected`，并只保存非敏感原因码：

- 客户经营店铺数或活跃 SKU 不符合 1–3 店、50–500 SKU 的 ICP，且不接受单店边界。
- 客户拒绝单主体、单店、最多 3 用户或纯只读范围。
- 客户要求绕过审批、验证码、限流、平台、银行、海关或数据控制。
- 客户要求假单、诱导评价、侵权、流量作弊或其他不进入本服务的经营方式。
- 客户要求保证盈利、自动接管或首期第三方写。
- 客户拒绝 Evidence、撤销机制、DPA、数据返还、保留或删除义务。
- 客户没有官方数据，也未指定运营和财务验收角色。
- 客户要求仓库或 TeamAgent 消息保存凭据、PII、银行资料或客户原始正文。

## 6. 缺失 Evidence 与准入决定

### 6.1 T0 阻断项

以下任一项缺失时，结论为 `preparation_only/input_not_ready`，T0 不开始：

1. 匿名 customer_ref、单一主体和单一 Ozon 店引用。
2. 50–500 个活跃 SKU 的官方目录或导出。
3. 至少一类官方订单或财务明细。
4. 至少 1 个 SKU 的正式成本 Evidence。
5. 分离的运营与财务验收角色。
6. 合法、最小权限、可撤销的只读授权或官方导出。
7. 客户级主协议、DPA、SOW 和退出附表签署引用。

### 6.2 非 T0 输入缺失

退货、结算、银行到账、FX、完整成本或费用字典缺失时，不猜数、不按零处理；相关字段
进入 `UNKNOWN/no_data/unallocated`，并记录 Owner、SLA、下一 Evidence 动作和复核条件。

### 6.3 最终资格结论

| 字段 | 结果 |
|---|---|
| qualification | `[qualified / preparation_only / rejected]` |
| input_readiness | `[ready / input_not_ready]` |
| rejection_reason_codes | `[NONE / CODE_LIST]` |
| missing_evidence_refs | `[NONE / REF_LIST]` |
| exact_scope_sha256 | `[SHA256_SLOT]` |
| input_manifest_sha256 | `[SHA256_SLOT]` |
| next_safe_action | `[SIGN_CONTRACTS / COLLECT_EVIDENCE / FREEZE_SCOPE / CLOSE]` |
| review_deadline | `[DATE]` |

## 7. 独立复核

| 角色 | 结论 | Evidence ref | 日期 |
|---|---|---|---|
| Commercial Owner | `[qualified/preparation_only/rejected]` | `[REF]` | `[DATE]` |
| Operations Reviewer | `[accepted/defects]` | `[REF]` | `[DATE]` |
| Finance Reviewer | `[accepted/defects]` | `[REF]` | `[DATE]` |
| Independent Verifier | `[passed/failed]` | `[REF]` | `[DATE]` |

# ADR-0098：董事会战略收敛与企业角色编制 v2

## 状态

Accepted for BAS-223 engineering implementation. Business Truth、真人任命、预算、CASH_VERIFIED、C0、SaaS 发布与外部写授权均未由本 ADR 产生。

## 背景

KJDS 已存在 18 个核心岗位、12 个 AI 专家、5 个独立控制角色、Team Control Tower 和 Enterprise AI ERP 静态合同。BR-148 首版可以确定性列出 35 个测试角色，但 `active_test` 与 `test_principal_ref` 容易把能力目录误解为已创建身份；企业画像八项中只有阶段、市场和平台显著改变编制。当前真实瓶颈仍是一个 Truth SKU 的 Product→Supplier→Order→Settlement→Bank→Actual Cash CM3 与商业 C0，而不是新增组织或自治层。

## 决定

1. 当前定位冻结为证据优先、真实现金导向、受控自动化的跨境经营控制面；长期企业 AI ERP 只保留为 Gate 后目标。
2. `EnterprisePositioningAdvisor.position(profile)` 保持唯一外部 Interface。八维角色、容量、席位、缺岗、冲突和下一激活角色全部留在 Module Implementation 内；HTTP 与 Web 仅为 Adapter。
3. 35 个条目是能力模板，不是 Principal、Agent 或真人岗位实例。删除 `test_principal_ref`，使用无企业身份含义的 `role_template_ref`；推荐状态为 `required_now/supporting_ai/on_demand/standby`，缺岗独立使用 `unsupported_gap`。
4. v1 只从版本化注册表读取当前画像。POST 接受完整画像并返回确定性模拟，不持久化、不创建第二画像账。
5. 当前 `solo_to_micro` 画像最多投影四个真人责任席位；席位是兼岗建议，不是 Appointment Evidence。既有六条 SoD 保持不可绕过。
6. 保留独立只读 GET/POST Interface，并复用现有 `/team-control` 页面展示；TeamControlTower 不吸收角色编制逻辑，页面不新建第二总控真源。
7. 双线容量采用 80% Truth/Cash/C0、20% 角色系统，90 天冻结 World Model、Venture Federation、Synthetic Economy、多市场和长期 Agent 扩编。

## 方案比较（best_solution_v1）

### A. 独立定位 Interface + 现有老板页 Adapter（选择）

- 符合深 Module：一个 Interface 覆盖八维规则，调用者无需理解实现。
- 复用当前认证、停写、OpenAPI、老板页与移动/可访问性合同。
- 不引入数据库、迁移或第二任务/身份/事实权威；可逆且总拥有成本最低。

### B. 把定位投影并入 `TeamControlTower.brief`（拒绝）

- 会把不依赖店铺 exact-scope 的企业模拟与 Team Control 的经营 scope/continuation 耦合。
- 增大严格响应合同和失败面，角色规则变化会无必要地使总控 continuation 漂移。

### C. 仅保留离线文档并延后系统接入（拒绝当前切片）

- 成本最低，但不能满足已拍板的 API+老板页内部验证目标，也无法机器验证八维画像是否真正生效。
- 若 API/Web 的维护成本连续两轮不能提高 Gate 通过率，应回退到此选项。

## 权威与失败边界

- 注册表、API、页面和测试均不证明真实原件已交付、真人已到岗或现金已验证。
- `enterprise_ref` 只进入画像和内容哈希，不映射 ApiKey、tenant、store 或权限。
- 未支持国家/平台只报告缺岗，通用角色不得冒充本地专业权威。
- 计算型 POST 可在 Kill Switch engaged 时运行，但认证和路由角色仍失败关闭。
- 任何 extra 字段、重复 market/platform、注册表漂移、未知角色或越权 true 均返回校验失败。

## Frontier technology review

`not_required`。本切片不新增或升级依赖、模型、外部 Provider、数据库、运行时或平台权限；只复用现有 Python/FastAPI/Next.js、版本化 JSON、OpenAPI 和 Team Control Adapter。

## 失效条件与复审

- 若一个 Truth SKU 和商业 C0 均通过，可评审企业画像持久化、受控 Appointment/Identity Authority，但必须另立 requirement/ADR/migration。
- 若 30 天无 `CASH_VERIFIED`，暂停新增角色系统能力；若 60 天无有效设计伙伴数据共享，保持内部工具定位。此时只允许无收费、无生产授权的设计伙伴问题验证，不得继续对外销售或交付收费诊断服务。
- 复审日：2026-09-13；Owner：Product Governance + Enterprise Architecture；独立复核：Risk + QA/Release。

## BAS-223 验收合同

- GET/POST 必须认证并复用相同读角色；POST 为无持久化计算，在停写状态可用，但不得调用写服务。
- Pydantic 输入/输出 `extra=forbid`；无效画像返回 422。输出必须校验 35 模板唯一与计数守恒、2–4 席与最低责任一一对应、六条 canonical SoD、来源 bundle 与 snapshot 哈希。
- 禁止动作必须逐项显式为 false：Identity、Agent、Appointment、Role binding、Task、Budget、Approval、Permit、Production authority、Fact promotion 与 External write。
- OpenAPI 保存快照必须与运行时一致；`/team-control` 只渲染服务端顺序和结论，展示作用域/边界/哈希，并区分能力模板、真人任命、AI 支撑与生产授权。
- Web 必须通过 390px、键盘、语义标题、live status、错误隔离与恢复焦点；推进动作只在相同 logical payload 的不确定网络失败时复用幂等键，确定性响应或 payload 变化必须清缓存。

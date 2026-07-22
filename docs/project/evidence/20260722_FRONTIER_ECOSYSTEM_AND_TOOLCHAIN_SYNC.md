# 2026-07-22 前沿生态、采集链与本机工具栈同步证据

| 字段 | 值 |
|---|---|
| evidence_id | KJDS-OPS-20260722-FRONTIER-TOOLCHAIN |
| recorded_at | 2026-07-22T20:23:48+08:00 |
| status | `partial_pass / real_external_inputs_blocked / requires_review` |
| formal_fact_promoted | `false` |
| actual_promoted | `false` |
| payment_or_procurement_enabled | `false` |

## 结论

本轮没有再建后台、审批、Gate、事实库或工作流 Owner。KJDS 模块化单体继续独占 Evidence → Approval → DecisionPacket → ExecutionPermit → `authorize_action()` → Readback；n8n 仍只负责既有计时与通知。新增成果是把 2026-07-22 官方/开源生态、现有 OpenClaw/Hermes/ComfyUI、1688 真实回读以及完整采集链统一纳入“先复用、代表性实测、按结果晋升”的合同。

首个真实 SKU 闭环仍未完成：Ozon 连续至少 28 天官方研究数据缺获批只读身份或原始导出；RU-001 的冻结询价已真实发送并通过服务端消息 ID 回读，供应商只回复“您好，稍等”，正式书面报价仍为 0。该回复只能证明送达和确认，不能形成价格、交期、库存、采购或 `actual`。

## 外部生态快照

机器可读快照位于 [`../registries/cross_border_automation_ecosystem.json`](../registries/cross_border_automation_ecosystem.json)，覆盖 GitHub、官方规范、npm、PyPI、MCP、OpenClaw、ClawHub、Hermes、浏览器 Harness、跨境 CLI/App/Agent/Skill/MCP 与工作流。

新增权威源随后做了真实强制刷新：47 个来源全部进入本轮检查，23 个新事件，46 healthy、1 failing。OpenCLI、Playwright、Stagehand、browser-use、Skyvern、Triton Windows 和 ComfyUI Manager 的 GitHub Release 源均成功；唯一失败仍是既有 Amazon SP-API RSS 的 HTTP 403，已独立记录为来源失败，不能解释为“无更新”。

已按层区分：

- Commerce exchange：UCP `v2026-04-08`、ACP beta；
- Delegated payment mandate：AP2 `v0.2.0`，只借鉴授权意图设计，不启用付款；
- Agent interoperability：A2A `v1.0.1`，没有外部独立 Agent 边界前不引入；
- Tool/UI：MCP Apps stable spec `2026-01-26`，可作为以后非技术 Evidence/Readback 显示适配器，但不拥有审批；
- Agent/UI protocols：AG-UI `release/2026-07-15`、A2UI 无 GitHub Release，保持观察；
- Implementations：OpenAI Agents SDK `v0.18.3`、Microsoft Agent Framework `python-1.12.0`、GitHub Agentic Workflows `v0.82.14`、DBOS Python `2.28.0`、Trigger.dev `v4.5.6`。

这些项目不被拼成第二控制平面。只有出现可量化缺口时，才选择一个最小组件：Agent handoff/guardrail 缺口优先评估 OpenAI Agents SDK；Python/Postgres 崩溃恢复缺口优先对 DBOS 做 ADR/隔离 PoC；多源 schema evolution 达到实测瓶颈后再评估 `dlt`。

## 完整采集链

注册表新增 22 个连续环节，每个环节均有 `primary`、`fallback`、`owner`、`boundary`、`status`、`verification` 和 `provenance`：

1. 来源权威/许可；
2. 账户/会话范围；
3. 官方 API/导出；
4. 确定性登录浏览器；
5. AI 浏览器后备；
6. 原始响应/下载/截图/DOM 留存；
7. 文件类型、恶意内容与隐私；
8. 解析器/schema 版本；
9. SKU/供应商规范身份；
10. 分页、时间窗、时区与控制总数；
11. 哈希、去重与变更历史；
12. 字段来源、置信度与 UNKNOWN；
13. 独立复核；
14. Evidence 与 lineage；
15. research/formal/actual 晋升门；
16. 漂移、隔离、回放与金样；
17. 限流、重试、熔断、会话过期与人工接管；
18. 服务端回读与对账；
19. 保留与撤销；
20. 监控、SLO 与事件；
21. 人工分钟与总成本；
22. 复用资产登记。

采集 lane 固定为：官方 API/导出 → 专用 KJDS Profile 的确定性适配器 → AI 浏览器隔离后备 → 登录/MFA/CAPTCHA/账户歧义时可见人工接管。任何 collector 只能生成 immutable research artifact；不能创建 formal fact、Approval、Permit、采购、付款、Listing 或广告。

## 本机实测结果

### OpenClaw

- 版本：`2026.7.1-2 (0790d9f)`；Gateway 仅 loopback；
- 外部插件 allowlist：Brave、Codex、Feishu、Firecrawl、Parallel、Tavily；
- Brave/Feishu/Firecrawl/Parallel/Tavily 为 `2026.7.1`，Codex 为 `2026.7.1-1`；
- `plugins doctor`：0 issue；
- `research` 技能：57 total、26 eligible、7 visible、0 missing requirements；
- 安全审计：0 Critical、5 Warning、2 Info。Skill allowlist 不等于 host-exec/MCP 权限隔离；当前只能按单一可信操作员使用。

### Hermes

- 版本：`v0.19.0 (2026.7.20, 86fb0463)`；
- 依赖审计：129 个组件、0 已知漏洞；
- skills/memory 写入审批、agent-created skill 保护与 checkpoint 已开启；
- `oss-forensics`、`watchers` 已移除；
- 当前默认模型最小调用实际返回 HTTP 429“余额不足或无可用资源包”。这证明失败被真实回读，不证明模型可用；
- 更新后的组合 MCP 测试尚未取得完整通过记录，保持 `requires_review`。

### OpenCLI 与浏览器采集 lane

- 当前官方仓库为 `jackwener/OpenCLI`，隔离安装包为 `@jackwener/opencli@1.8.6`，npm production audit 为 0 vulnerability；
- 官方扩展 `1.0.22` 的 SHA-256 为 `9d2e3d053948beab5d97124aa79b1532d2122e33e461eca56cac113afd33207a`；扩展拥有 `debugger`、cookies、tabs、downloads 和 `<all_urls>` 等高权限，因此禁止加载到主 Edge Profile；
- `opencli --version` 和 1688 命令面已通过；代表性只读命令 `opencli 1688 item 38547222320 -f json --trace retain-on-failure` 真实返回结构化 `BROWSER_CONNECT`/exit 69，耗时约 46 秒，未连接 Browser Bridge；
- 该失败按 hard stop 保存，未猜测修补适配器、未访问主 Profile、未重发 RFQ、未采购、未付款，也未晋升任何 formal fact/actual；
- 六个 OpenCLI Codex Skill 已按 `v1.8.6` 安装，后续每个成功路径必须沉淀 adapter/site memory/task sitemap/fixture/failure signature/replay test；
- Playwright `v1.61.1` 是确定性底座；Stagehand `3.7.0`/server `v3.7.4`、browser-use `0.13.6`、Skyvern `v1.0.47` 仅作为隔离候选，不形成第二浏览器平台。

### ComfyUI

- 官方 ComfyUI：`v0.28.2` / `306af3a8771a8232d26bd20acbfc6b07f862ad2b`；
- Manager：`3f159c5f651f6f3cf14ee0d51267bc433ade9a85`；
- loopback `8189`，默认 trusted 白名单 1186 nodes，core 回滚模式 807 nodes，两个模式均由修改后的启动脚本真实启动并读取 `/object_info`；
- Manager 禁止任意 Git URL 与 pip 安装；
- `triton-windows 3.7.1.post27` 经同一 Flux2 潜变量、同一 VAE、`cache-none` 的 30 对 A/B：两组均 30/30 成功；baseline 中位 `381 ms`，patched `476.5 ms`，patched 慢 `25.07%`；像素差异 PSNR `61.16 dB`，无业务质量收益；
- Triton 保留为显式实验能力，不进入默认 workflow，也不绕过 Windows Application Control；
- 合成图片已隔离为 synthetic test fixture，不是 RU-001 Evidence、Listing 资产或业务验收。真实素材能力仍等待供应商授权原图。

私密原始记录位于 Git 忽略的 `.runtime/real-sku-startup/`，包含 1688 消息回读、OpenCLI 安装/失败验收和 ComfyUI A/B 记录及 SHA-256；不提交账户信息、浏览器 Profile 或 Cookie。

## 结果验收与复利

每个工具按“安装 → 可启动 → 代表性任务 → 业务效果 → 失败/回滚 → 跨 SKU 复用”逐级验收。只有最后几级通过，才进入默认路径。

每次运行必须沉淀：适配器或明确缺口、字段映射、原始/标准化金样、失败签名与接管规则、回放测试、Evidence/Readback 模板、人工分钟与机器成本。量化目标为：

- 第二个同类 SKU 流程/适配器复用率 ≥70%；
- 第三个 ≥85%；
- 第三个 SKU 人工分钟 ≤ 第一个的 50%；
- 已知失败复发率 <5%；
- 重复外部动作 =0；
- 未经复核事实晋升 =0；
- 回滚成功率 =100%。

本轮已经形成可复用资产：生态注册表、22 环节采集合同、浏览器权限边界、RU-001 回读范式、OpenCLI 的版本/扩展哈希/BROWSER_CONNECT 失败签名/Skill 资产、Comfy 技术金样与失败签名、双模式启动脚本、A/B 阈值、回归测试和运行手册。由于第一个完整 SKU 仍被真实外部输入阻断，人工分钟的首轮基线尚不能虚构。

## 剩余阻断

1. Ozon 官方连续至少 28 天原始导出，或获批只读 API 身份；
2. RU-001、RU-002、RU-003 的带日期正式书面报价及原始附件；当前不重复催发已确认的 RU-001；
3. 供应商授权的真实商品、包装、配件和工厂素材；
4. 专用 KJDS Edge Profile 的两次重启、每平台 10/10、账户与商品 readback 验收；
5. Hermes 明确 Provider 路由后的本地与默认模型复验，以及逐个 MCP 当前版本复验。

在这些输入到达前，`formal_fact_promoted=false`、`actual_promoted=false` 保持不变。

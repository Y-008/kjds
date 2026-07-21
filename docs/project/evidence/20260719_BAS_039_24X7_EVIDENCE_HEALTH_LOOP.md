# BAS-039 24×7 Evidence 巡检接入

## 结论

既有 `scripts/run-24x7-health.ps1` 现在会分页调用控制平面的 Evidence 完整性巡检，而不是只检查 HTTP 存活。健康循环不新增调度器，继续把脱敏 JSON 与非零退出交给现有 Windows Task/OpenClaw 外层消费。

本轮只使用合成 Evidence、隔离 PostgreSQL 和本机回环 API；未读取真实 Ozon 凭证，未连接 Ozon，也未执行上架、改价、广告、采购或付款。

## 身份与失败关闭

- 使用独立 `KJDS_MONITOR_API_KEY`。
- 脚本要求该 key 在 `KJDS_API_KEYS_JSON` 中存在、actor 非空且唯一角色恰好为 `monitor`。
- key 与 operator、executor、pilot-reader 或 Ozon 平台凭证相同即拒绝运行巡检。
- 缺 key、身份映射错误、API 失败、分页超过上限、分页未完成或发现任一异常，均在 `-ControlPlaneOnly`/必需模式下退出码 2。
- 页大小与最大页数必须分别处于 `1..1000`，非法文本或越界值不会被静默转换。
- 输出只包含页数、扫描数、异常数、Incident 数和最后一份扫描报告 ID；不输出凭证、原始 Evidence 正文、finding 明细或实际哈希。

## 分页与自生成数据

- Evidence Service 支持排除指定 `source` 后再计算 `total`、读取页和生成 `next_offset`。
- Monitor 固定排除 `evidence-integrity-monitor`，因此每页新写入的扫描报告不会改变当前轮次的待扫描集合。
- 默认页大小 500、最多 20 页，最大覆盖 10,000 条非监控 Evidence；超过范围失败关闭，要求运维方调整有界配置或分批处理。
- offset 分页不承诺跨页全局数据库快照；业务并发写入显著时应重新从 0 执行一轮。

## 测试与故障注入

- 两页模拟 API：完整扫描后退出 0，两个 POST 均只使用 monitor key。
- monitor 同时带 admin 角色：调用前拒绝，零次巡检 POST。
- monitor 与 operator 复用：调用前拒绝，零次巡检 POST。
- 第二页返回损坏 Finding：完成分页但退出 2，只输出 `invalid=1`、`incident_count=1`，不泄露 Evidence/Incident ID。
- 重复主动扫描：monitor 自身报告不进入后续扫描总数，原异常复用同一未关闭 Incident。

## 验证结果

- PowerShell 语法：健康脚本与 G-1 脚本均通过 Parser。
- 健康循环定向测试：4 passed。
- Evidence Monitor 定向测试：2 passed；组合定向为 6 passed。
- 全量 Python/G-1：201 passed；另有 1 条既有 Starlette/httpx 弃用警告。
- Web：6 passed；生产构建通过。
- Ruff：通过。
- G-1 内密钥扫描：283 个非忽略工作区文件通过；写入本证据文档后复扫为 284 个通过。
- G-1：`PASS`，`evidence_integrity_monitor=true`，`evidence_integrity_health_loop=true`。
- 隔离恢复 SHA-256：`d2db7263ab46f6e3aab1d2d7644406790a9f2b4e6c421fc92bf6a3a6cac435d8`。
- 恢复计数：`products=4`、`orders=0`、`evidence_records=21`、`read_only_pilot_runs=1`。
- G-1 进程、数据库、备份和临时文件清理均为 true。

第一次完整 G-1 正确发现健康脚本仍指向默认端口 8000，而隔离 API 使用 8010，因此以 FAIL 结束且完成清理。将 `KJDS_CONTROL_PLANE_URL` 显式绑定到隔离 API 后，从头重跑完整 G-1 才取得上述 PASS；未将第一次失败隐藏或视作环境噪声。

## Review 结论

- Spec Review：满足 BR-027；未扩大为自动修复、删除、Kill Switch 释放或外部平台动作。
- Correctness Review：分页、页界、身份独占、凭证复用、异常发现和非零退出均有自动测试。
- Architecture Review：完整性判断仍归 Evidence Service，Monitor 负责编排，健康脚本只负责触发和摘要，不复制领域算法。
- Security Review：专用最小角色、凭证隔离与脱敏输出均失败关闭。
- Evidence Review：单元故障注入、真实隔离 API 调用、PostgreSQL 恢复与完整 G-1 共同支撑交付。

## 未完成边界

- “24×7”仍依赖现有 Windows Task/OpenClaw 实际持续运行；本次没有证明机器关机、休眠或宿主故障时仍可执行。
- 尚未验证 Slack、邮件、短信或电话等外部通知送达、升级和确认闭环。
- 尚无跨页一致性快照；高并发写入期间应重复整轮扫描。
- 发现异常只开 Incident 并失败退出，不自动修复、删除、覆盖 Evidence 或释放 Kill Switch。

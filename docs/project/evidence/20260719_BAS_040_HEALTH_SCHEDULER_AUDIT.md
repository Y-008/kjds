# BAS-040 Evidence 健康循环调度审计

## 结论

`run-24x7-health.ps1` 和默认安全的 Windows Task 管理合同已通过工程与 G-1，但截至 2026-07-19 03:31（Asia/Shanghai）尚未部署为 Windows Task 或 OpenClaw 定时任务。当前没有可支持真实运行的专用 monitor 配置，因此状态为 `BLOCKED_CONFIG`，不是 DONE，也不是 24×7 已上线。

本次仅做只读审计，没有创建、启用、修改或删除任何 Windows Task/OpenClaw 任务，没有读取或输出任何凭证值。

## 已实现的部署防护

- `scripts/manage-evidence-health-task.ps1` 默认 `Plan`，只输出版本化的预期定义，并明确 `mutation_performed=false`。
- 只有显式 `Install` 才能进入注册路径；安装前必须存在 Git 忽略的项目 `.env`，并清除当前终端的相关临时环境变量后重跑 `run-24x7-health.ps1 -ControlPlaneOnly`，防止“当前终端能跑、计划任务不能跑”的假预检。
- 任务 Action 固定为当前 `pwsh.exe`、当前健康脚本、当前仓库工作目录和 `-ControlPlaneOnly`；参数不得包含 KJDS/Ozon key、token、secret 或 password。
- 默认每 15 分钟运行，最长 5 分钟，同一任务重叠时 `IgnoreNew`；注册后立即回读定义，漂移时非零退出。
- `Audit` 复验启用状态、执行器、参数、工作目录、触发间隔、执行上限、重叠策略、最近结果和 Task Scheduler Operational 事件 102。只有最近结果为 0 且连续三条完成历史为 0 才返回 `accepted`；历史日志不可用也不降级为成功。
- 本轮只执行 `Plan`、不存在任务的 `Audit` 和隔离目录中的失败安装预检；没有执行真实 `Install`。

## 验证结果

- `uv run ruff check .`：通过。
- `uv run pytest -q --basetemp <project-runtime>`：206 passed，1 条既有 Starlette/httpx 弃用告警；其中任务管理合同的 5 项专测覆盖默认 Plan、安装前失败关闭、参数下界、三次成功验收和携密定义拒绝。
- Web：6 passed。
- `uv run python scripts/verify_secrets.py`：287 个未忽略文件通过，未回显秘密。
- 完整 `scripts/verify-g1.ps1`：PASS；`evidence_integrity_monitor=true`、`evidence_integrity_health_loop=true`、`evidence_health_task_contract=true`。
- 恢复演练：迁移 `20260718_0036`，4 个 Product、0 个 Order、21 个 Evidence、1 个只读 Pilot Run 精确一致；最新备份 SHA-256 为 `475928c0208399e80e5e1d6ceba1c9a89a6465ab01e2d24570e541bf769acdbb`。
- G-1 清理：进程、临时数据库和受管临时文件均成功清理。

## Windows Task 事实

- 未找到 Action 引用 `D:\KJDS\kjds\scripts\run-24x7-health.ps1` 的任务。
- `KJDS-Authority-Radar` 为 Ready，命令指向 `run-authority-radar.ps1`，最近一次结果为 0，下一次保持 30 分钟节奏；它不是 Evidence 健康循环。
- `OpenClaw_Wealth_Factory_24x7` 与 `OpenClaw_Wealth_Factory_v2` 均为 Disabled，命令指向另一工作区的 `job-wealth-factory.ps1`，不能算作 KJDS 健康任务。
- `OpenClaw Gateway` 处于 Running，但网关运行不代表存在健康循环定时定义或成功历史。

## OpenClaw 配置事实

- 对 `D:\AI\Apps\OpenClaw`、`D:\IT\OpenClaw` 与 `C:\Users\Lunar\.openclaw` 做只返回文件名的固定字符串检索。
- 未发现任何文件引用 `run-24x7-health.ps1`。
- 未打印 `openclaw.json` 正文，避免无关配置或敏感字段进入日志。

## 配置可用性

- 项目根目录当前没有 `.env`。
- 当前进程未配置 `KJDS_CONTROL_PLANE_URL`。
- 当前进程未配置 `KJDS_API_KEY`。
- 当前进程未配置 `KJDS_MONITOR_API_KEY`。
- 当前进程未配置 `KJDS_API_KEYS_JSON`。
- 当前进程未配置 `KJDS_HEALTH_REQUIRED`。

以上只记录“是否配置”，没有读取、复制或输出任何值。

## 部署验收条件

1. 持续运行的控制平面 URL 已冻结且 `/health/ready`、`/v1/operations/readiness` 可用。
2. operator 与 monitor 使用不同凭证；monitor 在凭证映射中唯一角色为 `monitor`。
3. `KJDS_HEALTH_REQUIRED=true`，页大小与最大页数处于安全范围。
4. 先手工执行 `run-24x7-health.ps1 -ControlPlaneOnly` 并取得退出码 0。
5. 复用 Windows Task Scheduler 或现有 OpenClaw 调度，不引入第二套调度器。
6. 任务 Action 精确指向当前仓库脚本，隐藏运行，不在参数中携带密钥。
7. 至少连续三次完成记录返回 0；同时完成一次受控失败演练，确认非零结果可见且输出脱敏。
8. 只有完成定义、载荷、运行历史与清理审查后，才能把 BAS-040 改为 DONE。

## 当前阻塞

需要运行配置所有者提供或批准：持续控制平面地址、独立 operator/monitor 身份映射及本机安全注入方式。缺少这些条件时注册任务会持续失败并制造虚假运维噪声，因此本轮明确不安装。

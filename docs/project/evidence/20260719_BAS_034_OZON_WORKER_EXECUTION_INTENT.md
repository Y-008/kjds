# BAS-034 Ozon Worker 显式执行意图与执行时复验

| 字段 | 值 |
|---|---|
| 状态 | DONE_ENGINEERING |
| 日期 | 2026-07-19 |
| Gate | G0 前置工程门，不构成 G0 放行 |
| 事实晋升 | false |
| requires_review | true |
| 真实 Ozon 调用 | 未执行 |
| 平台写操作 | 未执行 |

## 问题

BAS-033 已让标准 PowerShell 入口默认只执行离线预检，但 Worker 模块本身仍保留“未声明模式即联网”的旧默认行为。直接运行 Python 模块可绕过包装层的 `-Execute`；而预检和执行使用两个容器时，配置也可能在两次运行间变化。

## 已实现合同

- Worker CLI 必须且只能选择 `--preflight` 或 `--execute`；缺失或同时指定均由参数解析器失败关闭。
- Compose 只读 Worker 的生产命令显式包含 `--execute`，不存在隐式联网默认值。
- `--execute` 在当前进程、当前环境中先重跑连接环境校验，再构造控制平面或 Ozon HTTP 客户端。
- 首次单 SKU、无游标、默认分页的执行会完整重跑 BAS-033 离线预检；后续已批准批次仍复用通用连接安全校验，不破坏现有批次能力。
- 远程控制面明文 HTTP、非官方 Ozon origin、路径漂移、凭证缺失或复用均在网络客户端创建前拒绝。

## 验证结果

- 定向预检/执行意图测试：26 passed。
- 完整 G-1：PASS，`ozon_pilot_preflight=true`、`ozon_worker_execution_intent=true`。
- 全量 Python：186 passed（另有 1 条既有 Starlette/httpx 弃用警告）；Web 身份安全：6 passed。
- 生产 Ozon Worker 镜像：缺少模式时非零退出；不安全远程 HTTP 控制面在网络客户端创建前非零退出；输出未包含合成凭证。
- 密钥扫描：276 个非忽略工作区文件通过。
- 隔离恢复 SHA-256：`ecef7c7880030087dc47cf6a54cd6fff4363d12ff1b7887ea9891affe84ca6b8`；数据库、进程与临时文件均完成清理。
- 机器报告：`.runtime/G1_VERIFICATION.json`。

## 边界

- 显式 `--execute` 代表技术执行意图，不等于账户负责人批准；真实调用仍必须通过已激活 Pilot、独立 Review、Kill Switch 和 `OZN-003` 最小权限身份。
- 本增量没有读取、生成、轮换或撤销任何 Ozon Key，没有访问真实 Ozon，也没有发布 Listing。
- 该复验防止配置漂移与包装层绕过，不证明真实 API 响应、商品可售性、供货、合规或利润。

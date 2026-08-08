# BAS-215B 全域 AI ERP 六投影接入团队总控工程 Evidence

| 字段 | 值 |
|---|---|
| task | BAS-215B |
| date | 2026-08-08 |
| status | DONE_ENGINEERING candidate; release and business truth not claimed |
| owner thread | `019fd4c1-60c9-79a0-9338-8c204ba0f312` |
| machine-CAS commit | `56e36c44e4eb47dbc87df92a74c50e13cd105b76` |
| implementation base sampled | `9de4a366084f4422a3f58e92c7a5998c98615821` |
| database / migration / G-1 | not run; not changed |
| router / API / OpenAPI / Web | not changed |
| external write / Fact / Finance / Approval / Permit | false |

## 1. 本次证明的工程结果

`EnterpriseAiErpProgram.project()` 在 BAS-215A 的三个既有结构投影之外，新增
`integration_queue`、`capacity_risk` 和 `next_release_train`。三个字段只描述 WBS DAG、
并发/容量红线和每周两次集成列车政策；执行、当前占用、可用容量、列车日期、候选和 Gate
均保持 `UNKNOWN/NOT_STARTED/null`。

`TeamControlTower.brief(...)` 通过具名构造依赖读取该构造后零 I/O 的 Program，并白名单输出
六个顶层字段：

1. `squad_readiness`；
2. `role_conflicts`；
3. `parallel_execution`；
4. `integration_queue`；
5. `capacity_risk`；
6. `next_release_train`。

Tower 校验 Program contract ID/version、四个来源哈希、source bundle、内容寻址 snapshot、
固定计数、六字段动态真相和 fail-closed authority envelope，并把 BAS-215A 已复核的 registry、
source-bundle、compiled snapshot 三个 SHA-256 固定为受信合同。只修改 Squad/SoD/DAG 后重算
自报哈希的投影仍失败关闭。六个投影及 Program registry、
source bundle、snapshot 进入既有 `decision_basis_sha256`；Program 语义变化使旧 continuation
失效，单纯 `as_of` 变化仍只改变审计快照。`advance`、OperatingTask/Event 和外部
`brief/advance` Interface 没有新增命令或旁路。

runtime 只实例化 `EnterpriseAiErpProgram` 并注入现有 Tower。scope-invalid 在读取
OperatingTask、Benchmark、Settlement 或 Program 前返回六个显式 UNKNOWN 投影，Program
调用计数为 0；依赖未注入时显示 `enterprise_ai_erp_program_unavailable`，已注入但合同漂移
时失败关闭。

## 2. exact write set 与当前源码哈希

| 路径 | SHA-256 |
|---|---|
| `apps/control_plane/enterprise_ai_erp_program.py` | `d8d59f289d814b1c6ae9cca8c5389d1f5681155f6ec3d06c5ea57bdd586d7206` |
| `apps/control_plane/team_control_tower.py` | `caeeef180549b0fd2d72e4e31740a8770742a288f19ade83be14631064579c9c` |
| `apps/control_plane/runtime.py` | `19bca2e9416345c876ce487b3080e3bd0b8feb789689e0186a195022935ae47f` |
| `tests/test_enterprise_ai_erp_program.py` | `18d1d09b239489b2cd3750c9f54fdfcac16868c98beee487424141cd48198947` |
| `tests/test_team_control_tower.py` | `18cedc8f69878a210f554a2ab64ddd936ea1e394d674e5bce237c634d21f92b8` |
| `docs/project/MASTER_SPEC.md` | `288e98e2ff63b31d6c2e6b2e8d010eee778496fba9301739c9088ccd27a2f96e` |
| `docs/adr/ADR-0095-global-expert-council-and-portfolio-orchestration.md` | `8e358b84eb272c17a8e05ff7b8cdd6edede1546a6c6ad62c39499f08c26c96e6` |
| `docs/project/18_TEAM_CONTROL_TOWER.md` | `ec278e6f65f50131205ab015832cc3fdb951bd784d0bdcab0708212669870aed` |

本 Evidence 是第九个路径，不自引用自己的 SHA。BAS-216B 的 Lane L 控制/功能字节和其他用户
未跟踪资料不属于本写集。

## 3. 负向控制

- scope 无效：Program、OperatingTask、Benchmark 和 Settlement 均零读取；无 continuation；
- Program 缺失：六投影为 UNKNOWN，不猜造结构或状态；
- contract ID/version、source bundle、snapshot 或 control envelope 漂移：失败关闭；
- 修改 Squad title/Owner、SoD rule、integration DAG 或 reason code 后重封：受信合同不匹配并失败关闭；
- Squad 动态状态被提升为 VERIFIED、parallel policy 被放宽或静态字段缺失：失败关闭；
- Program registry/snapshot 合法变化：决定基线与 continuation 同时变化，旧 continuation 被拒；
- 输出不含真人绑定、当前任务、已验证 Evidence、Gate PASS、成熟度完成或外部写权威；
- 静态 `first_acceptance_contract` 仍是验收条件，不是结果；
- 本模块未创建 OperatingTask、Fact、FinanceEntry、Approval、Permit、凭据或外部动作。

## 4. 验证回执

| Gate | 原样结果 |
|---|---|
| Python compile | exit 0 |
| Ruff exact Python set | `All checks passed!` |
| Program + Tower focused | superseded by P1 closure run: `116 passed in 2.32s` |
| Program + Global Expert + Team Control/API adjacent | superseded by P1 closure run: `133 passed in 9.43s` |
| owned pytest basetemp cleanup | every run returned `CLEANUP=True` |
| secret verifier | `Secret scan passed: 1431 non-ignored worktree files and 1420 historical paths checked` |
| BAS-215B new local links | 3 checked, 3 present |
| broad modified-doc link scan | 136 checked; two pre-existing MASTER_SPEC baseline misses outside BAS-215B remain |
| `git diff --check` / cached check | exit 0 / exit 0; staged empty |
| PostgreSQL / Alembic / G-1 | not run |

首轮未指定 basetemp 的 Tower 测试有 27 passed、10 setup errors；十项错误均来自不可访问的
`C:\Users\Lunar\AppData\Local\Temp\pytest-of-Lunar`，不是产品断言失败。随后所有权明确的
`D:\KJDS\.runtime\bas215b-*` basetemp 重跑已通过并清理，因此不把首轮环境错误记为 PASS。
广域文档扫描发现的两条基线缺口是 MASTER_SPEC 中旧 BAS-123/BAS-125 链接多出
`project/` 前缀；本切片没有把它们误记为通过，也没有扩写集修复。BAS-215B 新增的 ADR、
运行手册和 Evidence 三条本地链接均已逐项回读存在。

## 5. 前沿技术 freshness

本切片属于本地、provider-neutral 的静态合同投影，不需要安装 Agent 协议、SDK、GraphRAG、
托管 Eval 或新的可观测性依赖。2026-08-08 对直接相关的跨 Agent/任务协议做官方一手资料
复核，结论为 `checked_no_change`：

- A2A 官方最新稳定线为 v1.0.1；协议不定义 KJDS 的 scope/revocation/business authority，
  继续 `watch`，本切片不发布 Agent Card、不联网委派；来源：
  <https://github.com/a2aproject/A2A/releases>、
  <https://a2a-protocol.org/latest/announcing-1.0/>；
- MCP core 2026-07-28 已稳定，但 Tasks 仍是 opt-in extension，独立规范/实现成熟度仍不构成
  KJDS canonical task authority；继续 `watch`，OperatingTask/Event 保持唯一真源；来源：
  <https://modelcontextprotocol.io/specification/2026-07-28>、
  <https://modelcontextprotocol.io/extensions/tasks/overview>、
  <https://tasks.extensions.modelcontextprotocol.io/specification/draft/tasks>。

决策、风险与生产边界未变化，因此不修改
`docs/project/registries/frontier_technology_adoption.json` 的 `reviewed_on/as_of`，避免虚假刷新。

## 6. 仍未证明

工程通过不证明以下经营或组织事实：14 个领域角色/8 个 Squad 真人到岗、当前没有职责冲突、
有三个空闲 Writer、EAERP WBS 已启动或完成、M0–M4 已晋级、下一集成列车已排期或通过发布
Gate、真实 SKU 现金闭环、设计伙伴、C0、生产 SLO、Top1、任何付款/合同/平台写权限。它们
继续由既有真人、OperatingTask、Evidence、Finance、Release 和外部平台权威保持
`UNKNOWN/BLOCKED_EVIDENCE`。

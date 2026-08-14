# BAS-109 · 治理事实作用域投影

| 项 | 结果 |
|---|---|
| 记录时间 | `2026-07-28T11:07:09+08:00` |
| 分支 | `feature/batch-opportunity-mining-059` |
| 基线 HEAD | `b34a3a7`（当前 0.59 集成工作树尚未提交） |
| 版本 | API/Web `0.59.0` |
| 范围 | BR-084 / BAS-109 / ADR-0034 |
| 外部写 | 全部关闭 |

## 结论

M0 已用一个 `GovernanceScopeAuthority` 深模块替换 Truth/Governance 中的递归
`store_ref` 搜索。任意 JSON 中出现店铺字符串不再构成授权关系：

- Gate Review 必须由其完整 Evidence 集合证明当前 tenant/entity/store；
- Execution Plan 必须由冻结 `evidence_ids` 证明同一作用域；
- Command 只能继承精确匹配的 scoped `plan_id`；
- 已有 Receipt 还必须有自身当前且 scoped 的 Evidence；
- Observation/Readback Window 必须同时匹配 scoped plan 与 command；自身有 Evidence
  时同样单独复验。

旧投影若有顶层 `store_ref`，它只能收窄作用域且必须精确匹配，不能替代 Evidence。
未绑定、孤儿父 ID、父链错配、跨店、坏回执 Evidence 或 authority 故障均被排除并返回
Owner/SLA/next blocker。该模块只读，不创建 Gate 决定、Approval、Permit、Readback、
Compensation 或任何外部写。

## Truth/Governance 合同

认证快照新增：

- `authority_hashes.governance_scope_sha256`
- `governance.scope_authority.contract_id/status/counts/excluded_counts`
- scoped governance source gaps/blockers

后续 Approval、Permit、Readback、Kill Switch 与 Compensation 状态只从该模块已经通过
作用域验证的集合计算。Kill Switch 继续是全局安全收紧控制，不能被 scoped projection
用来放宽。

## 自动化验证

```text
uv run ruff check apps/control_plane/governance_scope.py \
  apps/control_plane/truth_governance.py \
  tests/test_governance_scope.py tests/test_truth_governance.py
All checks passed

uv run pytest -p no:cacheprovider --basetemp=.tmp/pytest-governance-scope \
  tests/test_governance_scope.py tests/test_evidence_scope.py \
  tests/test_truth_governance.py tests/test_scope_grants.py -q
24 passed

uv run python scripts/verify_secrets.py
Secret scan passed: 641 non-ignored worktree files and 581 historical paths checked

uv run ruff check .
All checks passed

uv run pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-local
629 passed, 1 existing deprecation warning

cd web && npm test && npm run build
50 passed; Next.js production build passed

git diff --check
passed
```

测试证明：完整 scoped Evidence + 精确父链可稳定投影；嵌套 JSON 里的店铺字符串不能
使记录入账；跨店 plan、孤儿 command/window、坏 Receipt Evidence 均失败关闭；缺
entity authority 时模块不会读取全局 authority 集合，避免泄漏其他租户的记录计数。

## 真实运行

真实 `ozon-primary` 仍没有正式 entity grant，系统没有为了展示“已治理”而读取或
归属全局历史记录。固定 `as_of=2026-07-27T02:00:00Z` 的认证结果：

```text
entity_scope.status=no_data
governance.scope_authority.status=no_data
reviews=0 plans=0 commands=0 windows=0
source_gap=governance_entity_scope_authority_missing
observe_research=ready
candidate_score=research_only
pilot_approve=blocked
external_publish=blocked
external_writes=false
```

相同请求重放得到相同 `snapshot_sha256`。四个容器全部 healthy，API 实际加载
`kjds-governance-scope-authority-v1`，Alembic current/head 均为单一
`20260727_0056`。

## 构建与 Gate 边界

标准 Dockerfile clean build 再次因 Docker Hub 对 `python:3.12-slim` 的 manifest
请求 `EOF` 失败。运行烟测继续从当天已验证的本地 API 镜像派生，只覆盖已通过全量
门禁的 `governance_scope.py/truth_governance.py`，没有改写容器或数据库。网络恢复后
仍须完成标准 API/media-worker clean rebuild，临时派生镜像不构成 Release 镜像验收。

后续 BAS-110 于 `2026-07-28T11:19:19+08:00` 已在网络恢复后完成标准 Dockerfile
API 与 media-worker clean build 并重启健康，故该临时构建缺口已关闭。

- 0.59 PM/RA Release Gates 继续 `REJECTED`。
- Pilot/Final Gates 未通过。
- Ozon、供应商消息、采购、付款、库存、价格和广告写入仍关闭。
- pricing 继续 `not_for_sale`。

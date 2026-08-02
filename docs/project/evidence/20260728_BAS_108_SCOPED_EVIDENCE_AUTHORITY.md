# BAS-108 · 经营 Evidence 作用域权威

| 项 | 结果 |
|---|---|
| 记录时间 | `2026-07-28T11:00:06+08:00` |
| 分支 | `feature/batch-opportunity-mining-059` |
| 基线 HEAD | `b34a3a7`（当前 0.59 集成工作树尚未提交） |
| 版本 | API/Web `0.59.0` |
| 范围 | BR-084 / BAS-108 / ADR-0034 |
| 外部写 | 全部关闭 |

## 结论

M0 已增加单一 `ScopedEvidenceAuthority` 深模块。它不建立第二套 Evidence 表，也不从
`tenant_ref` 猜测经营主体；其唯一公开接口按显式 `as_of` 将现有不可变 Evidence
投影到认证 Principal、正式 entity grant 和请求店铺：

- 新 Evidence 可使用 `kjds-evidence-scope-v1` 直接冻结
  `tenant_ref/entity_ref/store_ref` 与独立 Reviewer；
- 旧 Evidence 不被改写，只能由独立 A 级
  `kjds-evidence-scope-binding-v1` Evidence 按 target ID/hash 补作用域；
- 原件完整性先于作用域判定；
- 缺正式 entity grant 为 `no_data`，旧原件未绑定为 `partial/unbound`；
- 跨 tenant/entity/store、target hash 不同、自审或损坏原件为 `blocked`。

`TruthGovernanceService` 动态消费该模块并增加
`authority_hashes.evidence_scope_sha256`。作用域未 ready 时，
`observe_research` 仍可继续，`candidate_score=research_only`，
`pilot_approve=blocked`；客户端不能重算 readiness。

## 真实运行结果

当前真实 `ozon-primary` 没有被伪造的组织主体授权或经营 Evidence 绑定。认证请求
在固定 `as_of=2026-07-27T02:00:00Z` 下返回：

```text
overall_status=ready_with_constraints
entity_scope.status=no_data
entity_ref=null
evidence_scope_sha256=null
source_gap=evidence_scope_not_bound
observe_research=ready
candidate_score=research_only
pilot_approve=blocked
external_publish=blocked
external_writes=false
```

同一请求重放的 `snapshot_sha256` 完全一致。匿名请求为 `401`，授权身份请求为
`200`，越权店铺为 `403`；运行 OpenAPI 将该 GET 路由声明为 `KjdsApiKey` 认证。

## 自动化验证

```text
uv run ruff check apps/control_plane/evidence_scope.py \
  apps/control_plane/truth_governance.py \
  tests/test_evidence_scope.py tests/test_truth_governance.py
All checks passed

uv run pytest -p no:cacheprovider --basetemp=.tmp/pytest-evidence-scope \
  tests/test_evidence_scope.py tests/test_truth_governance.py \
  tests/test_scope_grants.py -q
20 passed

uv run python scripts/verify_secrets.py
Secret scan passed: 638 non-ignored worktree files and 581 historical paths checked

uv run ruff check .
All checks passed

uv run pytest -q -p no:cacheprovider --basetemp=.runtime/pytest-local
625 passed, 1 existing deprecation warning

cd web && npm ci && npm test && npm run build
50 passed; 0 vulnerabilities; Next.js production build passed

git diff --check
passed
```

回归覆盖直接作用域、旧原件独立 A 级绑定、未绑定、正式 entity grant 不自动升级
旧 Evidence、跨店、错 target hash、自审、损坏 Blob、匿名 401、越权 403、
rule gap、profit no_data 和固定 `as_of` 确定性。

## PostgreSQL 与运行容器

- Alembic head/current：单一 `20260727_0056`
- `postgres/api/web/media-worker`：全部 healthy
- `/health/ready`：`version=0.59.0`、database `ok`
- API 容器实际加载：
  `ScopedEvidenceAuthority.CONTRACT_ID=kjds-scoped-evidence-authority-v1`

原冻结三条 Marketplace Observation 未改变：

- snapshot `mos_893969993df54dc9ab0ead01c588a215`
- snapshot SHA-256
  `91c1c4114830b249abe9183d9ed1702ab9623e6b4039e9831850aae5be02a4e1`
- Evidence `evd_294c9c496acb4c25bd74bccd92b18780`
- Blob SHA-256
  `0d8e17d3191d42572dec874d459686c4c0d6f3948354cff8195297252c307812`
- item count `3`
- item SHA-256：
  `2f18ac875e737eba84987f279f6eb4ea9f5a9a2c95f448ed7833cc4c30b74504`、
  `5d652608a84aed15f603d6a25ec43612f05057752d7fd7724e71a84c24566171`、
  `69c79e876f3a2c9c17688e11b25a467014596bb7efec592a298e918838f3fe92`

## 构建缺口与 Gate 边界

标准 Dockerfile clean rebuild 在本次验证时连续三次因 Docker Hub manifest/blob 请求
`EOF` 失败；既有容器和数据库未受影响。为验证真实运行，只从当天已验证的本地
`kjds-api` 镜像派生，精确覆盖已通过全量门禁的
`evidence_scope.py/truth_governance.py` 两个模块并重建 API 容器。正式发布前仍必须在
网络恢复后完成标准 API/media-worker clean rebuild；该本地派生烟测不能冒充发布镜像
验收。

- Ultimate Start PM/RA 仍只表示允许 M0→M4 实施。
- 0.59 PM/RA Release Gates 继续 `REJECTED`。
- Pilot/Final Gates 未通过。
- Ozon、供应商消息、采购、付款、库存、价格和广告写入仍关闭。
- pricing 继续 `not_for_sale`。

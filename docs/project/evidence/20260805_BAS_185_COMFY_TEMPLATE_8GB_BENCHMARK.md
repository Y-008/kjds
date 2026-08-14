# BAS-185 — ComfyUI 商品模板与 8GB 基准（A：合同/合成回放）

## 1. 结论

本切片建立 `GovernedComfyTemplateBenchmarkWorkspace.evaluate(...)` 的离线、确定性、只读合同，用仓库自有合成 fixture 验证固定模板、typed parameters、8GB runtime/run receipt **形状**、资源计量、合成 license/SBOM 绑定、现有 Media QA 引用和零权限包络。它不连接当前 ScopeGrantAuthority 或独立 license authority。

本结果仅为 **contract/synthetic Observation**：

- `candidate_state=not_admitted`；
- `real_8gb_status=UNKNOWN`；
- `production_admitted=false`；
- `current_scope_authority=blocked/UNKNOWN`；
- `current_runtime_authority=blocked/UNKNOWN`；
- `independent_run_authority=blocked/UNKNOWN`；
- `independent_license_authority=blocked/UNKNOWN`；
- 不调用 ComfyUI、Provider、网络或数据库；
- 不创建或修改 ContentAsset、Evidence、Fact、Approval、Permit、Pilot、Outbox；
- 不改变 `image_execution.py`、`media_workbench.py` 或任何生产模板准入状态。

真实 8GB GPU 样本、真实图片质量、真实峰值显存、真实延迟/成本、独立人工 Media QA、生产回滚演练和生产模板扩签仍为 UNKNOWN/未满足。

本机只读枚举（2026-08-05）显示 `NVIDIA GeForce RTX 4060 Laptop GPU, 8188 MiB, driver 595.79`。这只证明设备描述符可见，不是本 benchmark 的 runtime/run receipt，也没有执行 ComfyUI workload。Fixture 的 `required_gpu_bytes=8 * 1024^3` 是 repository-owned synthetic **exact 8 GiB（8192 MiB）** profile；8188 MiB 与 8192 MiB 相差 4 MiB，不能被本切片自动视为同一硬件 class 或真实 8GB 通过。后续硬件样本票必须显式冻结硬件 class、允许区间/保留显存语义和独立权威 receipt，再实际测量 peak/latency/quality；本切片不猜测二者等价。

## 2. 唯一接口与真源边界

唯一模块接口：

```python
GovernedComfyTemplateBenchmarkWorkspace.evaluate(
    template_ref,
    fixture_ref,
    runtime_receipt,
    run_receipts,
) -> ComfyTemplateBenchmarkObservation
```

服务器加载 repository-owned registry/fixture；调用方没有 `workflow` 参数，不能提交任意 ComfyUI workflow JSON、custom node、模型下载地址或 Provider 凭据。

生产真源保持不变：

| 领域 | 唯一既有真源 | 本切片行为 |
|---|---|---|
| 生产 Comfy workflow | `apps.control_plane.image_execution.ComfyImageExecutionService._workflow` | 只引用，不修改 |
| 生产模板准入 | `apps.control_plane.media_workbench.TEMPLATE_CATALOG` | 只核对 champion，不新增 admitted 项 |
| Scoped factory 模板投影 | `scoped_media_factory.py` 复用 `TEMPLATE_CATALOG` | 不修改 |
| 图片 QA | `content_growth.REQUIRED_QA + IMAGE_QA` | 动态导入并精确核对八项规则，不复制审核权威 |
| 产物/Evidence/Lineage/Manifest | 现有 ContentAsset、Evidence、QA、Manifest authority | 零写入 |

Registry 中的 template 是 `shadow_candidate`，且固定：

- `production_admitted=false`；
- `workflow_download_allowed=false`；
- `custom_nodes_allowed=false`；
- `benchmark_registry_is_production_truth=false`；
- `production_catalog_write_allowed=false`。

未来 C 切片若要形成生产准入，必须另行扩签并直接修改现有 `image_execution.py` workflow compiler、`media_workbench.py` canonical catalog 及既有测试；不得把本 benchmark registry 旁挂成第二生产真相。

## 3. 合同与确定性编译

Registry 冻结：

- template ID/version/champion ref/lifecycle；
- workflow contract SHA-256、core node allowlist；
- typed parameter schema 与上下界；
- model artifact digest（本合成模板为 `core-no-model-download`）；
- pinned core node bundle digest；
- license IDs、SBOM SHA-256、QA profile；
- 固定 8GB workload、显存/延迟/自动指标阈值；
- 不可交换 hard Gates 与全部 false 的 authority flags。

Fixture 冻结：

- synthetic tenant/entity/store/scope-binding 字段；
- data-as-of；
- typed parameter set 与确定性 compiled workflow SHA-256；
- runtime receipt、2 次 warmup、5 次 measurement；
- 每次 run 的显存 allocated/reserved、wall latency、OOM、partial failure、retry/downgrade、输出 SHA-256 和自动指标；
- `all_measurements` 选择规则，禁止挑样；
- 合成数据、零客户数据、零秘密、零 Provider ID。

Registry 与 fixture 都使用 UTF-8、sorted-key、compact JSON 语义计算 `content_sha256`；每个 runtime/run receipt 另有 canonical `receipt_sha256`。默认构造器还把两份 repository-owned content seal 编译进模块，内容漂移或自重封新内容均不能替代默认真源。

## 4. 8GB 与运行收据 Gate

合成 runtime receipt 必须精确包含并绑定：

- GPU descriptor 与 `total_vram_bytes=8 GiB`；
- driver/CUDA/ComfyUI/Python/OS profile；
- model、core node bundle、node registry、environment digest；
- repository-owned synthetic license shape、其 canonical attestation hash 与 SBOM；
- resolution、batch、seed、warmups、repeats、sample selection；
- recorded/effective window 与 synthetic scope-binding 字段。

这些字段只证明 fixture 内部结构和哈希一致，不证明 grant 在可信当前时间仍有效，不证明 runtime/run receipts 来自当前独立硬件权威，也不证明许可证已由独立法务/合规 authority 复核。`current_scope_authority`、`current_runtime_authority`、`independent_run_authority` 与 `independent_license_authority` hard Gate 均固定为 blocked；未来真实样本票必须注入服务器构造的 Principal/store context、`ScopeGrantAuthority.current(trusted_now)`、独立 runtime/run receipt authority 与独立 license receipt authority 后才可改变状态。

每个 run receipt 必须精确绑定 runtime/environment/parameters/compiled workflow，并满足：

- 2 个 warmup 与 5 个 measurement 全部存在、索引唯一；
- measurement 全部进入 aggregate，warmup 不进入；
- 非负有限显存/延迟，allocated ≤ reserved ≤ 8 GiB；
- `OOM=false`、`partial_failure=false`；
- `retry_count=0`、`automatic_downgrade=false`；
- 输出 SHA-256 与自动指标完整；
- receipt hash、scope、authority、版本、时态均未漂移。

NaN、Infinity、负数、超过 8GB、超时、OOM、partial、自动重试、自动降级、缺 warmup/repeat、重复 index、挑样、hash/version/schema/scope/time 漂移均 fail closed；任何一项不能由平均质量分抵消。

## 5. QA、许可、回滚与准入

自动指标是 Observation，不是 QA authority。本模块始终要求现有八项 Media QA 与独立人工 review。以下每项都是独立 hard Gate：

1. synthetic scope binding（仅合成形状）；
2. current scope authority（本切片固定 blocked/UNKNOWN）；
3. registry/fixture/hash/version；
4. typed workflow compiler/node allowlist；
5. synthetic runtime receipt shape；
6. current runtime authority（本切片固定 blocked/UNKNOWN）；
7. synthetic run receipt shape/resource envelope；
8. independent run authority（本切片固定 blocked/UNKNOWN）；
9. synthetic license/SBOM shape；
10. independent license authority（本切片固定 blocked/UNKNOWN）；
11. existing Media QA authority；
12. real 8GB sample；
13. independent human review；
14. rollback exercise；
15. production catalog expansion approval；
16. production admission boundary；
17. zero authority。

此外，`production_admission_boundary` 永久把 A 切片标记为 `synthetic_contract_slice_not_production_evidence`。该边界不影响“合成合同是否正确回放”的判定，但始终阻止其成为生产准入证据。

即使测试 seam 把所有合成 admission booleans 设为 true，本 A 切片仍返回 `not_admitted/UNKNOWN/production_admitted=false`，防止合成数据或模型自评直接晋级。

## 6. 隐私、作用域与副作用

- synthetic tenant/entity/store/authority-binding 任一漂移时，runtime/run receipt hashes 不投影；这不是 current authority 证明；
- runtime/run 输入递归拒绝 secret、Bearer、email/customer canary、Provider request ID 类字段；
- Observation 仅包含 safe code、hash、计数、版本与状态；
- 不包含 runtime body、input image ref、模型输出正文或用户素材；
- side-effect flags 固定全部 false；
- 模块无 Provider client、HTTP client、SQL repository 或执行入口。

## 7. 验收矩阵

Focused tests 分层覆盖：

- repository seals 与 deterministic replay；
- 唯一 evaluate 接口与任意 workflow 拒绝；
- custom node/model download/caller workflow 拒绝；
- typed parameter 每类边界；
- tenant/entity/store/authority、future/stale receipt；
- 假 8GB、model/node digest、NaN/负数/超阈值；
- OOM/partial/retry/downgrade/sample picking；
- warmup/repeat 完整性；
- license/SBOM；
- current scope/runtime、independent run/license authority 始终 hard-block/UNKNOWN；
- real sample/review/rollback/catalog approval 逐项 hard block；
- quality score 不替代人工 review；
- secret/customer-data canary；
- Media QA 真源引用与所有 side effects=false。

最终 literal 命令和文件 SHA-256 在冻结 Gate 后记录于本任务 handoff；本文件不把尚未执行的真实 GPU 基准写成事实。

## 8. Rollback

本切片无数据库、API、runtime composition、依赖或外部副作用。回滚只需删除本任务精确五文件；生产模板、ContentAsset、Evidence、QA、Manifest 和 Provider 状态无需恢复或补偿。

## 9. UNKNOWN 与下一阶段

保持 UNKNOWN：

- 真实 8GB GPU 的 peak allocated/reserved VRAM；
- 本机 8188 MiB 设备是否属于后续批准的“8GB card”硬件 class；
- 真实 driver/CUDA/ComfyUI/model/node 组合；
- 当前 ScopeGrantAuthority receipt、独立 runtime/run authority receipt 与独立 license authority receipt；
- 真实图片效果、八项人工 QA、失败分布；
- 真实 p50/p95 latency、吞吐、成本与最大损失；
- 生产 rollback 实演；
- production template admission。

下一阶段 B 只能引入独立权威签发的真实 8GB runtime/run receipts 与真实样本；下一阶段 C 必须经过独立 review 后扩签现有生产真源，才可讨论 production admission。

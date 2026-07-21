# 2026-07-18 图片内容证据闸门验证

| 项目 | 结果 |
|---|---|
| 需求 | G2 商品图片真实性、素材权利与生成血缘 |
| 状态 | PASS（工程合同）；真实 SKU 素材尚未录入 |
| 数据迁移 | 无；复用 ContentAsset、Passport 与 Evidence |
| 自动测试 | 140 passed |
| Lint | PASS |
| G2 | NOT_STARTED |

## 验收目标

1. 商品图片不得由纯文本凭空重建商品本体。
2. 图片 Brief 必须引用已批准 Passport 中的真实样品图或授权原图，以及素材权利证据。
3. 只允许 `retouch`、`composite`、`infographic` 三种受控模式，并显式锁定商品事实。
4. 生成结果必须先成为哈希有效的不可变 Evidence；媒体类型、来源图片、处理方式、生成时间和 ContentAsset ID 必须匹配。
5. 图片除通用五项 QA 外，还必须通过商品一致性、来源血缘和文字/参数准确性检查；任一失败即退回。

## 验证结果

- 缺少 `source_asset_evidence_ids` 的图片 Brief：拒绝，PASS。
- 原图或权利证据不属于已批准 Passport：服务层拒绝。
- 生成结果不是图片、来源不匹配、ContentAsset ID/模式不匹配或缺少处理元数据：服务层拒绝。
- `product_fidelity=false`：状态进入 `qa_failed`，不能批准，PASS。
- 已批准资产不能被新生成结果覆盖；失败资产允许修正后重新提交。
- `uv run ruff check .`：PASS。
- `uv run pytest -q --basetemp <仓库内独立临时目录>`：140 passed；保留 1 条既有 Starlette/httpx 弃用警告。
- `git diff --check`：PASS。

## 当前边界

本次只建立可执行合同，不代表已有真实样品图、供应商素材授权或 Ozon 可发布素材，也不放行 G2。前三个 SKU 继续使用现有图像工具；只有形成跨 SKU 稳定批量工作流后才接入 ComfyUI MCP。当前 Evidence Blob 适合试点规模，媒体量显著增长后再按既有架构迁移到对象存储，业务侧仍只保存证据引用。

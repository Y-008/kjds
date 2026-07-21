# BAS-023 图片 QA 与 Listing 草稿交接证据

## 结论

状态：`DONE`（工程合同完成，真实 SKU/Ozon 发布仍未放行）

- 图片 QA 必须一次提交适用的完整检查集；图片为通用五项加图片三项，共八项。
- 服务拒绝缺项、重复项、未知项、空审核说明和非法 Evidence ID 列表。
- 每项结果保存 `passed`、`notes`、`evidence_ids`、服务端 `reviewed_by` 与 UTC `reviewed_at`。
- 任一项失败进入 `qa_failed`；全部通过才进入 `approved`。
- Listing 草稿只能引用同一商品、类型为图片、状态为 `approved` 且已有产物 Evidence 的 ContentAsset。
- `listing_data.images` 必须与所列已批准 ContentAsset 的产物 Evidence 精确一致，并保存 `content_asset_ids` 血缘。
- 创建草稿只产生 `listing.publish` 待审批对象；没有调用 Ozon 写接口，也没有自动发布。

## 验证

- `uv run ruff check apps tests`：PASS。
- `uv run pytest -q`：148 passed；仅有既存 Starlette TestClient 弃用警告。
- `web/npm run build`：PASS，TypeScript 与生产构建通过。
- `./scripts/verify-g1.ps1`：PASS。
- G-1 报告：`.runtime/G1_VERIFICATION.json`。
- Alembic head：`20260718_0036`；本项复用现有 JSON 字段，因此没有新增迁移。
- 密钥扫描：246 个非忽略工作区文件通过。
- 隔离备份恢复：PASS，恢复 head 为 `20260718_0036`。

## 未被该证据证明的事项

- 没有真实 SKU 图片完成八项人工 QA。
- 没有真实俄语 Listing 或 Ozon 类目属性完成审核。
- 没有 Ozon 发布、库存、价格、广告或付款写入。
- 没有解除 `SKU-001/002`、`OZN-001/002` 和真实财务口径阻塞。

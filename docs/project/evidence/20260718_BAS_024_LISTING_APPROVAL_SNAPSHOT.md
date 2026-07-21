# BAS-024 Listing 审批不可变快照证据

## 结论

状态：`DONE`（审批快照合同完成；真实 Ozon 发布仍未放行）

- `listing.publish` 审批使用完整草稿内容的规范 JSON 计算 SHA-256。
- 摘要只包含商品、供应商报价、利润场景、目标平台和完整 `listing_data`；不包含时间、申请人、草稿 ID 或审批 ID。
- JSON 对象字段顺序不影响摘要；标题、描述、属性、图片或其他草稿内容改变时摘要改变。
- 审批 payload 保存草稿 ID、商品、报价、利润场景、标题、描述、类目、属性、内容资产 ID、图片产物 Evidence、CM3 和快照摘要。
- Web 为非技术审批人展示上述可读上下文，并明确“平台未写入”和“必须由不同身份审批”。
- 复用现有双人审批与自批拒绝能力；本项未增加 Ozon 发布执行器。

## 验证

- `ruff check apps tests`：PASS。
- `pytest -q --basetemp .runtime/<isolated>`：149 passed；仅有既存 Starlette TestClient 弃用警告。
- `web/npm run build`：PASS，TypeScript 与生产构建通过。
- `tests/test_sourcing.py`：验证字段顺序稳定、内容变化摘要改变、审批上下文和 `platform_write_executed=false`。
- `./scripts/verify-g1.ps1`：PASS；149 项测试、248 个非忽略文件密钥扫描、API/Web/PostgreSQL/迁移回放与隔离恢复均通过。
- 隔离恢复 SHA-256：`3a4d42405abdea3e08a04d442dd8c682487d0f7f4ee3c9c134a05fde642e2155`。
- Alembic head 仍为 `20260718_0036`；本项复用现有 Listing JSON 和 Approval payload，没有新增迁移。

## 未被该证据证明的事项

- 没有真实俄语 Listing、类目属性或图片完成经营负责人审批。
- 没有真实 Ozon 发布、回读、回滚或平台侧状态变化。
- 没有解除 `SKU-001/002`、`OZN-001/002` 和真实财务口径阻塞。

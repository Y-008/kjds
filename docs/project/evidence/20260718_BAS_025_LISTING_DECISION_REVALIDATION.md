# BAS-025 Listing 批准时快照复验证据

## 结论

状态：`DONE`（决定时复验完成；真实 Ozon 发布仍未放行）

- `listing.publish` 进入“批准”路径前，服务端从持久化存储重新读取 Listing 草稿。
- 草稿的 `approval_id`、审批 payload 的 `draft_id` 与审批资源必须相互匹配。
- 服务端重新计算完整草稿快照 SHA-256，并使用常量时间比较与审批请求中冻结的摘要核对。
- 摘要缺失、草稿不存在、资源不匹配或草稿内容变化时均失败关闭，审批不会变为 `approved`。
- “拒绝”路径不产生发布风险，可继续记录拒绝结论和原因。
- Approval 账继续作为批准/拒绝状态的唯一事实源，没有在 Listing 表复制第二份决定状态。
- 本项没有创建 Ozon 发布执行器、平台凭证调用或其他生产写入。

## 验证

- `ruff check`：PASS。
- `tests/test_sourcing.py tests/test_core.py`：20 passed。
- 测试覆盖摘要顺序稳定、内容变化、审批 ID 不匹配和决定时复验失败关闭。
- `web/npm run build`：PASS。
- `git diff --check`：PASS（只有既存 Windows CRLF 提示）。
- `./scripts/verify-g1.ps1`：PASS；149 项测试、249 个非忽略文件密钥扫描、API/Web/PostgreSQL/迁移回放与隔离恢复均通过。
- 隔离恢复 SHA-256：`7fdcf30b30ae050899c25e277203c4307bcc1bde0b5c7b1d6d6f526f77321859`。
- Alembic head 仍为 `20260718_0036`；本项不新增表或迁移。

## 未被该证据证明的事项

- 没有真实独立审批人对真实 Listing 做出结论。
- 没有真实 Ozon 发布、状态回读、失败补偿或回滚。
- G2 仍受真实 SKU、素材、类目与 Ozon 账号证据阻塞。

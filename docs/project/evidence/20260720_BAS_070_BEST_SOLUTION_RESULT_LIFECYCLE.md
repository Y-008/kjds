# BAS-070 最佳方案结构化结果与反方复核门

## 结果

`best_solution` 不再只有合同级提示词。分析表新增 `selection_assessment_json`，服务端要求：

- 每个注册方案逐条覆盖全部硬约束，保存 `passed` 与理由；
- 被选方案必须通过所有硬约束；
- 每个方案保存 Evidence 等级、长期风险调整价值、总拥有成本、最大损失、可逆性与回滚、价值实现时间、运维适配；
- 每个未选择方案恰好保存一个淘汰理由；
- 保存敏感因素、失效条件、复审时间、审批要求，以及不行动方案或缺失理由；
- 接受型独立复核至少提出一个反方解释；
- 正式决定仍然 `execution_eligible=false`。

## 工程边界

- 复用既有 Decision Contract、Analysis、Review 和 Resolution，不新建第二决策引擎或评分系统；
- 不使用等权总分，不把复杂度、技术新旧或代码量作为目标函数；
- 最佳方案不强制伪造数值预测；需要预测的问题继续使用既有预测合同；
- 页面使用原生结构化表单，不新增前端依赖。

## 迁移与验证

- 迁移：`20260720_0038`；生产前备份 SHA-256 `89f194a8f9f94582f70d03f6027e39f5779edd48693b0d34680e54a86a53f730`，源 head `20260719_0037`。
- 主数据库已升级到 `20260720_0038`。
- 隔离数据库已完成空库→0037→0038→0037→0038，并删除隔离库。
- 领域与合同定向测试：18 passed。
- Web 测试：15 passed；Next.js 生产构建与 TypeScript 检查通过。
- OpenAPI 快照已重新生成并由合同测试比对运行时 Schema。
- `uv run ruff check .`：通过。
- `uv run pytest -q --basetemp .pytest-tmp-full-0038`：295 passed；仅 1 条上游 Starlette/httpx 弃用警告。
- `npm test`：16 passed。
- `npm run build`：Next.js 生产构建与 TypeScript 检查通过。
- Docker API/Web 已重建；`/health/ready` 返回数据库健康，Web HTTP 返回 200。

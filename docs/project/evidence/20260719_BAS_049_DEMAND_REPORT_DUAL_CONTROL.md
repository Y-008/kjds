# BAS-049 Ozon 需求报告双人不可变复核

| 字段 | 值 |
|---|---|
| 日期 | 2026-07-19 |
| Gate | G0 / `SKU-000` |
| 状态 | DONE_ENGINEERING；BLOCKED_BUSINESS_INPUT |
| API 版本 | `0.36.0` |
| 业务事实晋升 | 否 |
| 平台写入 | 否 |

## 风险

`BAS-048` 已要求上传 Ozon Data、至少 28 天的报告，但这些字段仍由上传者声明。若上传动作直接满足 Gate，错误文件、公开样例或伪造元数据可能污染候选研究、询价与利润判断。

## 已实现合同

- 上传只创建不可变 `source_report` Evidence 和待复核状态，不满足 `SKU-000`。
- 只有 `approver` 或 `admin` 可以通过专用接口接受或拒绝；上传者与复核者必须是不同 `actor_id`。
- 复核生成独立 JSON Evidence，绑定原报告 ID、SHA-256、上传者、复核者、结论和理由，并同时写入 `reviews` 与 `review_attestation` 血缘。
- 同一复核者相同请求幂等返回；结论或理由改变会被拒绝，历史不覆盖。
- 单份报告至少一个有效接受且不存在有效拒绝才可满足；任一有效拒绝优先阻断。后续可上传一份新的、重新核对的报告重新进入复核。
- readiness 重新验证报告 Blob、来源、窗口、角色元数据、报告哈希、双人身份与复核 Blob，不信任页面状态。
- 通用 Evidence 接口禁止保留来源 `gate_requirement_review`，通用 Lineage 接口禁止直接连接 `gate_requirement` 或伪造 `evidence/reviews`；这些血缘只能由专用受权工作流产生。
- Web 将流程拆为“上传报告”和“独立复核”，显示上传者并明确上传不会解锁。

## 验收覆盖

- 只有上传：保持 pending。
- 上传者自审：422 阻断。
- 独立接受：该报告满足证据条件。
- 独立接受后另一个复核者拒绝：报告阻断。
- 同一复核者重复相同请求：幂等；改写结论：阻断。
- 公开样例或伪造来源：不计入。
- 普通 operator 通过通用 Evidence/Lineage 伪造复核：阻断。
- 只写入 `reviews`、缺少 gate attestation 的部分事务：失败关闭。
- 普通 operator 调用专用复核接口：403 阻断。

## 验证记录

- `uv run pytest tests/test_demand_report_gate.py tests/test_readiness.py --basetemp=.runtime/pytest-bas049-targeted`：11 项通过。
- `uv run pytest tests/test_reserved_evidence_workflows.py --basetemp=.runtime/pytest-bas049-reserved`：3 项通过。
- `uv run pytest tests/test_api_contract.py tests/test_demand_report_gate.py tests/test_readiness.py --basetemp=.runtime/pytest-bas049-contract`：14 项通过。
- `npm test`：8 项 Web 契约/身份安全测试通过。
- `npm run build`：Next.js 生产构建通过。
- `uv run ruff check .`：通过。
- `uv run pytest --basetemp=.runtime/pytest-bas049-final3-20260719`：231 项完整 Python 回归通过；因果实验测试固定测试种子以消除随机 SRM 偶发失败，生产分流与 SRM 阻断逻辑未改变；仅保留既有 Starlette `httpx` 弃用警告。
- `git diff --check`：通过。

## 未解除项

- 尚未取得账户主体导出的真实 Ozon Data 原报告，因此 `SKU-000` 仍是业务阻塞。
- 尚未由第二个真实审批身份读取并复核该报告。
- 人工复核提高证据强度，但不等于 Ozon 官方数字签名。若未来 API 返回稳定导出任务 ID、账户身份和可验证签名，应另立 ADR 评估自动来源证明。
- 本次不接受条款、不下载平台文件、不生成候选、不采购、不上架，也不执行任何 Ozon 写操作。

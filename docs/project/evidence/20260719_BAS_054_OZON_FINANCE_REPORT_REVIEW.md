# BAS-054 Ozon 财务报表独立复核门

## 结论

KJDS 已把 Ozon 费用、退货和结算导出的正式事实晋升改为失败关闭：原始 CSV/XLSX 可以上传、哈希固化并进入暂存区，但在非上传者完成来源复核前不得进入事实账。普通订单导入保持原流程。

这项能力没有取得任何真实店铺数据，也没有批准 Ozon 字段到会计科目的映射；它只建立真实原件到来后的可信入口。

## 合同

1. `/v1/imports/ozon` 保存原始文件 Evidence、SHA-256、导入类型和唯一 `source_for` 血缘，并按财务保留类别管理。
2. `/v1/imports/{import_id}/finance-review` 只允许 `reviewer`、`compliance` 或 `admin`，且上传者不能复核自己的文件。
3. 接受必须逐项确认：真实账户导出、报告期间匹配、不是公开样例、导出完整；任一项未通过只能拒绝。
4. 复核结论作为新的不可变 Evidence，同时链接原件和 ImportJob；同一复核人可以幂等重试，但不能改写既有结论。
5. 任一有效拒绝优先于接受；缺少接受、原件损坏、哈希不符、导入类型不符或血缘歧义都会阻断正式事实晋升。
6. 通用 Evidence 上传接口不能伪造复核来源，通用血缘接口也不能伪造 `reviews` 关系。
7. 复核只证明来源可信，不代表 `fee_type` 等字段已获得会计解释；真实费用字典仍需财务负责人另行批准。

## 验证范围

- 财务导入待复核时晋升失败；
- 独立接受后允许晋升；
- 上传者自审失败；
- 接受时任一检查未通过即失败；
- 同一复核幂等、变更结论失败；
- 先接受后任一独立拒绝仍阻断；
- 多个原件血缘造成歧义时失败；
- 普通订单导入不受财务门误伤；
- operator 不能调用财务复核接口；
- 通用 Evidence 接口不能伪造复核来源。

验证结果：

```text
uv run ruff check .
All checks passed

uv run pytest -q --basetemp .runtime/pytest-full-finance-review
259 passed, 1 existing Starlette deprecation warning

pwsh -NoProfile -File scripts/verify-g1.ps1
PASS；migration=20260719_0037；api_health=true；web_container_health=true；
backup_restore=true；formal_fact_promotion=true；finance_reconciliation=true；
ozon_worker_contract_test=true；ozon_response_integrity=true

git diff --check
PASS（仅既有 Windows CRLF 转换提示）
```

## 真实业务下一步

账户负责人从 Ozon 后台下载一个最短可核对期间的原始财务文件并由 operator 上传；另一名财务 Reviewer 对照后台期间和账户完成四项复核。只有通过后，财务负责人才能基于真实行样本设计费用代码映射并做首次三方对账。

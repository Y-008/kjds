# BAS-055 Ozon 财务复核 Web 交付

## 结论

KJDS Web 已把财务导入从模糊的“导入完成”改成可操作的双人交接：费用、退货和结算文件上传后只显示暂存结果、导入编号和“未入账”；另一身份的 Reviewer/Compliance/Admin 用户可读取该编号并保存四项来源检查及接受/拒绝结论。

复核通过仍不会自动晋升正式事实、批准会计字段或启动三方对账。普通订单文件不进入财务复核卡片。

## 验收边界

1. 上传成功保留 `import_id`、`record_type`、总行数、可解析行数和复核状态。
2. operator 会话只展示交接说明，不展示复核提交表单。
3. Reviewer/Compliance/Admin 会话可输入导入编号、读取状态并提交四项来源检查。
4. 接受与拒绝都通过既有专用 API 保存，服务端继续执行“上传者不得自审”和不可变结论约束。
5. 页面明确复核不等于入账；未增加事实晋升、映射批准或对账快捷操作。
6. 未引入新框架、状态库、接口或数据库迁移。

## 验证结果

```text
web: npm test
10 passed

web: npm run build
Next.js production build PASS; TypeScript PASS; 13 routes generated

uv run pytest tests/test_ozon_finance_review.py tests/test_reserved_evidence_workflows.py
10 passed

uv run ruff check .
All checks passed

uv run pytest --basetemp=.runtime/pytest-basetemp-<timestamp>
259 passed, 1 existing Starlette deprecation warning

git diff --check
PASS（仅既有 Windows CRLF 转换提示）

pwsh -NoProfile -File scripts/verify-g1.ps1
PASS；migration=20260719_0037；api_health=true；web_container_health=true；
web_tests=true；web_build=true；formal_fact_promotion=true；finance_reconciliation=true；
cleanup_processes=true；cleanup_database=true；cleanup_files=true
```

## 未完成的真实业务验收

- 尚未使用真实 Ozon 财务导出进行 operator → reviewer 双身份演练。
- 尚未批准真实费用代码到会计科目的版本化映射。
- 尚未执行订单—费用—结算—银行首次三方对账。
- 因此本交付证明的是受控入口和 Web 操作路径，不代表已经取得店铺财务数据或算出真实利润。

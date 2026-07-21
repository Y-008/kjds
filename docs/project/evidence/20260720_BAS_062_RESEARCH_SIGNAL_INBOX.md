# BAS-062：第三方研究信号收件箱验收证据

| 字段 | 值 |
|---|---|
| task_id | BAS-062 |
| requirement | BR-048 |
| status | DONE_ENGINEERING |
| date | 2026-07-20 |
| owner | 工程+商品 |
| migration | 无；复用 Evidence、Blob 与 Lineage |

## 交付结果

- 新增提供方无关的研究信号服务和 `/v1/market/research-signals` 专用 API。
- 固化原文件、提供方、稳定记录 ID、原始 URL、观察时间、服务端捕获时间、原始标量字段、许可状态和候选关联。
- 精确重试复用同一 Evidence；内容变化追加新 Evidence，不覆盖历史。
- 一条信号可关联最多 20 个稳定候选；候选过滤只读取对应血缘。
- 拒绝敏感原始字段、凭证查询参数、非法 URL、非法许可状态和无界元数据。
- 通用 Evidence 和 Lineage 入口拒绝伪造 `research_signal` 角色及其候选关系。
- Web 候选工作台提供非技术录入并明确显示“辅助资料”；不存在自动 Product、采购或 Listing 路径。

## 验收命令

```powershell
uv run ruff check .
uv run pytest
cd web
npm test
npm run build
```

## 验证结果

- Python：`282 passed`（公共临时目录权限异常后，改用项目私有 `--basetemp` 重跑通过）。
- Web：`12 passed`，Next.js 生产构建通过。
- OpenAPI：运行时与 `contracts/openapi-v1.json` 一致，版本 `0.40.0`。
- G-1：`PASS`；`research_signal_inbox=true`、`api_health=true`、`web_container_health=true`、`backup_restore=true`，迁移为 `20260719_0037`，临时数据库和进程已清理。

## 保留边界

- 本交付只证明研究信号可安全进入 KJDS，不证明第三方数据、公式或营销声明正确。
- 第三方资料默认 C/D 级，只有既有独立指标级权威复核可以在明确适用范围内批准 A/B。
- Seerfar Open API、妙手/51Selling 店铺连接和浏览器插件均未安装；正式连接器仍需许可、协议、字段、身份、速率、撤销、审计和真实样本对账。
- `SKU-000/001`、真实供应商报价、CM3、采购与 Listing 阶段门状态不变。

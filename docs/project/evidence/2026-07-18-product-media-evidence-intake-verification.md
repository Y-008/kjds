# 真实图片与权利证据入口验证

| 元数据 | 值 |
|---|---|
| 日期 | 2026-07-18 |
| 范围 | BAS-020 / G1 前置能力 |
| 结论 | 工程验证通过；业务资料未提交 |
| Gate 影响 | 不改变 G0、G1、G2 当前状态 |

## 已冻结合同

- `POST /v1/products/{product_id}/media-evidence` 必须成对接收真实商品图片与独立权利/授权文件。
- 图片只接受 JPEG、PNG、WebP；权利文件只接受 PDF、纯文本或 Markdown；服务端同时校验声明类型和文件签名。
- 每份原件由不可变 Evidence 保存并计算 SHA-256，记录 SKU、变体、素材角色、来源类型、来源引用和上传身份。
- 权利证据通过 `authorizes` 血缘连接到对应原图；原图和权利证据都连接到商品与 Quality Passport 草稿。
- 素材角色固定为主图、背面、侧面、细节、配件、包装和比例参照七类。
- 上传只追加 Quality Passport 草稿，不自动批准，也不调用图片生成服务。
- `GET /v1/products/{product_id}/media-readiness` 区分 `missing`、`captured_pending_passport`、`approved`；七类素材全部进入已批准 Quality Passport 后，`ready_for_full_production` 才为真。

## 操作入口

- Web 控制台：候选 SKU 下方“真实原图与权利证据”。
- API：`POST /v1/products/{product_id}/media-evidence`。
- 状态查询：`GET /v1/products/{product_id}/media-readiness`。

## 验证结果

```text
uv run ruff check .
All checks passed!

uv run pytest -q --basetemp .runtime/pytest-media-evidence-20260718-1
142 passed, 1 warning in 4.07s

npm run build
Next.js 16.2.10 production build passed, including TypeScript validation.
```

系统临时目录 `C:\Users\Lunar\AppData\Local\Temp\pytest-of-Lunar` 在首次全量测试时被 Windows 拒绝访问；使用项目内全新隔离 `basetemp` 后 142 项测试全部通过，未发现代码失败。

## 验证覆盖

- 七类真实素材逐项进入待审批状态。
- 三类 Passport 经独立审核批准后，七类素材 readiness 才整体放行。
- 伪装为 PNG 但签名不符的内容在创建任何 Evidence 前被拒绝。
- `automatic_generation` 始终为 `false`。
- OpenAPI v1 快照已同步。

## 明确边界

- 本次没有提交任何真实 SKU、商品照片或授权文件。
- 本次没有调用 ComfyUI、图片模型、MCP 图片服务或外部生成供应商。
- 工程入口完成不等于商品、合规、质量或 G2 内容 Gate 已放行。
- 下一阶段必须由业务负责人选择三个真实 SKU，并提交可追溯原图与权利文件；随后才可锁定 Image Brief，进入受控修图、背景合成和信息图生产。

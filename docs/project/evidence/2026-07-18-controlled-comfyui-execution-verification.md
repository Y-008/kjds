# 受控 ComfyUI 执行闭环验证

| 项 | 结果 |
|---|---|
| 日期 | 2026-07-18 |
| 范围 | `ozon-retouch-v1`、ContentAsset 执行状态、输出 Evidence 回收、Web 操作入口 |
| 结论 | 工程闭环通过；真实 SKU 与商品视觉验收未开始 |

## 冻结边界

- 唯一自动模板为 `ozon-retouch-v1`。
- 工作流只有官方核心节点：`LoadImage → ImageScaleToTotalPixels → SaveImage`。
- 输入必须是已经通过来源和权利校验的单张真实原图。
- 模板只做 Lanczos 4MP 等比保真处理，不加载生成模型，不改变商品结构、颜色、配件或文字。
- `composite` 与 `infographic` 只能建立 Brief；未经真实 SKU 模板复验不得执行。
- 输出进入不可变 Evidence 后仍处于 `generated`，必须通过 8 项 QA 与人工批准，禁止自动上架。

## 可复验证据

1. Alembic head：`20260718_0036`。
2. PostgreSQL：本地业务库从 `0029` 升级到 head 成功；`0036 → 0035` 回退成功；`0035 → 0036` 再升级成功。完整 G-1 隔离库还完成了从空库升级、回退到 `0024`、再升级。
3. 静态检查：`uv run ruff check .` 通过。
4. 完整测试：`147 passed`；另有一条 Starlette/httpx 弃用警告，不影响当前结果。
5. Web：Next.js 生产构建和 TypeScript 检查通过。
6. OpenAPI：运行时合同与 `docs/project/contracts/openapi-v1.json` 一致。
7. 完整 G-1：PASS；隔离备份恢复 SHA-256 为 `8087ceab63324b6888f4e0eaf11b8ee9c0a31045aeea16800aeac638bcf7616d`，恢复后商品/订单/证据/只读运行计数为 `4/0/19/1`。
8. 本机 ComfyUI：
   - 版本：`0.27.0`；
   - Prompt：`f0d6cec6-a436-456f-901b-d70363c4e28e`；
   - 状态：`success`；
   - 输出：`controlled-smoke_00001_.png`；
   - 输出大小：`760204` bytes；
   - SHA-256：`2e968e1690531230f4fa8394172b080d5d352116bd13017f8facdc379577ea71`。

## 未完成与禁止外推

- 烟测输入是用户提供的技术截图，不是商品原图，不能作为商品 Evidence、视觉验收或 Listing 素材。
- 当前没有三个真实 SKU、7/7 已批准原图和权利证据，因此没有执行真实商品任务。
- 没有完成视觉一致性、配件一致性、俄语文字准确性、平台规则或转化效果验证。
- 本结论不授权 Ozon 上架、改价、广告、付款或任何外部写操作。

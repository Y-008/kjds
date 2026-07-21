# 启动资料包 v2 图片素材合同验证

| 项目 | 结果 |
|---|---|
| 日期 | 2026-07-18 |
| 范围 | `sku-media.csv`、启动资料包校验器、私密副本准备脚本、Web 启动入口 |
| 工程结论 | PASS |
| 经营结论 | G0/G1/G2 未因此放行 |

## 验证目标

图片生成必须先有真实商品素材与合法使用依据。资料包 v2 为 RU-001、RU-002、RU-003 的 `base` 版本固定七类最小素材：

- `front_main`
- `back`
- `side`
- `detail`
- `accessories`
- `packaging`
- `scale_reference`

## 失败关闭规则

- 未知 SKU、重复的 SKU/版本/素材角色、缺失任一基础角色均拒绝；
- 状态只能是 `pending`、`captured`、`verified` 或 `rejected`；
- `verified` 只接受 `sample_photo` 或 `supplier_authorized`；
- `verified` 必须填写素材来源引用、授权证据引用、带时区的 ISO-8601 时间、64 位 SHA-256 与负责人；
- CSV 只记录引用和结构，不保存图片，不读取凭证，不上传素材，不晋升正式证据。

## 验证证据

- 公开模板结构校验返回 `contract=kjds-startup-package-v2`、`status=structurally_valid`；
- 覆盖报告返回 RU-001、RU-002、RU-003 均为 7 个基础素材角色；
- 负向测试删除 RU-003 的 `packaging` 后返回 `invalid`；
- 负向测试将缺少来源、授权、时间、哈希和负责人的素材标记 `verified` 后返回 `invalid`；
- 既有三 SKU×三供应商覆盖和敏感字段拒绝仍保留。

验证命令及结果：

- `uv run ruff check .`：PASS；
- `uv run pytest -q --basetemp <repo-runtime-temp>`：140 passed；
- `npm run build`：Next.js production build 与 TypeScript 检查 PASS；
- `git diff --check`：PASS。

## 未完成与真实边界

当前模板中的素材仍为 `pending`，没有任何真实原图、供应商授权、样品拍摄记录或哈希被提交。图片生成、质量审核、Ozon 上架和经营放行均未发生。下一步必须由商品负责人把真实文件放入私密工作区之外的受控原件存储，并把不可变证据引用填入清单后再走 Passport 与内容审核。

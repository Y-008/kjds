# 2026-07-18 启动资料包结构合同验证

| 项目 | 结果 |
|---|---|
| 状态 | PASS |
| 合同 | `kjds-startup-package-v2` |
| 文件数 | 6 |
| SKU 覆盖 | `RU-001`、`RU-002`、`RU-003` |
| 供应商覆盖 | 每 SKU 3 家不同供应商 |
| 正式事实晋升 | `false` |
| G-1 字段 | `startup_package_contract=true` |
| 自动测试 | 152 passed |
| 密钥扫描 | 265 个未忽略工作区文件 |

## 文件哈希

| 文件 | 行数 | SHA-256 |
|---|---:|---|
| `g0-governance.csv` | 6 | `e7815b16868350d66fedc090b1ef8216f0ebce09661cb47be6d7fb46b469ac30` |
| `g0-ozon-access.csv` | 9 | `7e937e635740bf8442a12d3015f363f1faa52050a95614b057e9199d174d166b` |
| `sku-passports.csv` | 3 | `4da91d0d04fa3d2805cab7282e4764cb2ab1febcc458f9d9ce6eeb433213d75a` |
| `supplier-quotes.csv` | 9 | `a3b6401c2f0f01ac0a48709642717966cbaaefa8fd2c4b09615ba6a38f4ba3e6` |
| `sku-media.csv` | 21 | `26823aaabe9dd29aa0bd45901d4b727db2a7b8bd2c46ec5ece2c25656c407ec9` |
| `finance-reconciliation.csv` | 1 | `e1049dd86710aa116f1ba385211320aa519457e62d62ba3c6ff7b9251e4da27a` |

## 验证范围

1. 六份文件名称和列顺序与冻结合同一致。
2. 治理和 Ozon 权限清单包含全部关键行且不重复。
3. Passport 模板包含三个唯一非空 SKU。
4. 报价模板引用已知 SKU，且每个 SKU 恰有三家不同供应商。
5. 每个 SKU 的基础版本覆盖七类图片角色，`verified` 素材必须带来源、权利引用、带时区时间、SHA-256 和负责人。
6. 内容预检逐行报告缺值、证据引用、负责人和未核验素材；严格模式在任一资料区未就绪时返回退出码 3。
7. 负向回归会拒绝缺失供应商/图片覆盖和 `api_key` 等敏感字段名。
8. 校验器只读 CSV，不写数据库、不读取引用内容、不自动导入、创建证据或晋升事实。

## 机器证据

- `uv run python scripts/validate_startup_package.py`
- `uv run pytest -q tests/test_startup_package.py`
- `.runtime/G1_VERIFICATION.json`

## 保留边界

`structurally_valid` 仅表示资料包可以进入后续人工/后端校验。它不证明字段真实、原件有效、合规结论正确，也不代表 G0/G1 已放行。

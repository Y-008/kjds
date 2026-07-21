# BAS-031 Ozon API 身份盘点合同验证

| 元数据 | 值 |
|---|---|
| 日期 | 2026-07-18 |
| Gate | G0 / OZN-003 |
| 状态 | DONE_ENGINEERING |
| 事实晋升 | false |

## 目的

把 Ozon Seller 只读观察到的多个宽权限 API 身份转换为可审计、无密钥的调用方盘点，而不是直接复用或在文档中保存凭证。

## 实现

- 启动资料包升级到 `kjds-startup-package-v3`，新增 `g0-ozon-api-identities.csv`。
- 每个身份仅记录平台脱敏引用或内部别名、用途、调用系统、Owner、角色数、权限分类、最后使用时间、处置决定、证据、复核人和状态。
- 公共模板预置七个非敏感身份别名，对应当前待盘点数量；不得把真实 Key、Client ID 或平台内部标识写入模板。
- 校验器要求至少一行、每行引用非空且唯一；所有未完成字段进入人工 intake 阻塞清单。
- `prepare-startup-package.ps1` 继续只补缺失模板，绝不覆盖已存在的私密资料。

## 验证

- 公开模板结构校验：`structurally_valid`，合同 `kjds-startup-package-v3`，身份覆盖数 7。
- `tests/test_startup_package.py`：4 passed；测试临时目录固定在仓库 `.runtime`，绕开 Windows 全局临时目录权限问题。
- 负向测试：空 `identity_ref` 与重复 `identity_ref` 均失败关闭。
- 完整 `scripts/verify-g1.ps1`：PASS；Alembic `20260718_0036`、153 项 Python 测试、6 项 Web 身份安全测试、272 个非忽略文件密钥扫描、生产 API/Web 容器、Compose 健康链和隔离恢复均通过。
- 最近一次隔离恢复 SHA-256：`196eada9aea90df1cb5f173d174935077aeb168d1bd24fad58dd2844f92b0b31`。

## 边界

本合同不证明任何身份仍在使用，不证明其权限符合最小化，也不会创建、读取、轮换或撤销 Ozon Key。完成 `OZN-003` 仍需要账户负责人填写脱敏盘点、提供原始证据并明确批准处置。

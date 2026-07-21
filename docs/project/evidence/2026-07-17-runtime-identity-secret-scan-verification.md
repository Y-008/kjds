# 运行身份与密钥扫描验证记录

| 元数据 | 值 |
|---|---|
| date | 2026-07-17 |
| scope | G-1 / BAS-013 / SEC-001 |
| decision | `docs/adr/ADR-0011-runtime-identity-and-secret-scan.md` |
| result | PASS |

## 已验证结果

- 空 `KJDS_API_KEYS_JSON={}` 在开发环境安全回退到 `KJDS_API_KEY`，不再生成零身份运行态。
- 非法 JSON、未知环境、未知角色、占位密钥、生产共享单密钥和未登记 Web 代理密钥均在启动时失败关闭。
- 运行摘要只包含环境、身份数、legacy 模式和角色组合，不输出密钥或连接字符串。
- 标准库扫描覆盖 226 个 Git 已跟踪或未忽略的新文件；禁止环境文件、私钥/证书容器、数据库备份和高置信 token 签名，报告不回显秘密。
- `scripts/start-kjds.ps1` 在启动服务前执行相同身份校验。
- G-1 在 PowerShell 7 下完成隔离 PostgreSQL、API、Web、身份校验和密钥扫描，最终 `runtime_identity_config=true`、`secret_scan=true`、`cleanup_processes=true`、`cleanup_database=true`、`cleanup_files=true`。

## 可重复命令

```powershell
$env:UV_CACHE_DIR = 'D:\KJDS\kjds\.runtime\uv-cache'
uv run python scripts/verify_secrets.py
uv run python -m apps.control_plane.security
uv run pytest tests/test_security.py -q -p no:cacheprovider
pwsh -NoProfile -File scripts/verify-g1.ps1
```

## 验收摘要

- 专项安全测试：14 passed。
- 完整回归：136 passed。
- 工作区密钥扫描：226 files checked。
- 完整 G-1：PASS，Alembic head `20260717_0035`。

## 保留边界

当前实现是单机/环境变量部署的最小安全门，不提供集中轮换、撤销、审计代理或 HSM。首次托管生产部署、身份数量明显增长或发生凭证事件时，必须重新评审 Vault/KMS 类能力。

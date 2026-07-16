# KJDS G-1 Environment Gate

这个文件不再保存会过期的手工 `PASS` 结论。G-1 状态必须由当前工作区的实时验证脚本产生：

```powershell
.\scripts\verify-g1.ps1
```

脚本会使用一个专用的临时 PostgreSQL 数据库，并验证：

- Alembic 全新升级、回滚和重新升级；
- Ruff 与全部 Python 测试；
- Next.js 生产构建；
- FastAPI 和 PostgreSQL 的真实读写及事件落库；
- Web 冷启动和页面指纹。

机器可读结果写入 `.runtime/G1_VERIFICATION.json`，该目录不进入 Git。只有当最新报告为 `PASS`，且报告中的 `git_commit` 与当前提交一致时，才能宣告 G-1 工程验证通过。

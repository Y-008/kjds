# OpenCLI 社媒只读接入验证记录

- 日期：2026-08-04
- 基线 HEAD：`7623d4f23c3cb7b0ff55e04076fd5d3162523751`
- 范围：仅自有抖音/小红书创作中心只读数据
- 外部写：`false`
- 媒体下载：`false`
- Cookie 导入：`false`
- 原始账号数据：仅保存在忽略目录 `.runtime/social-intelligence/opencli/**`

## 运行时供应链

| 组件 | 固定版本/摘要 |
| --- | --- |
| OpenCLI | `@jackwener/opencli@1.8.6` |
| Browser Bridge | `1.0.22` |
| 扩展发布包 SHA-256 | `9d2e3d053948beab5d97124aa79b1532d2122e33e461eca56cac113afd33207a` |
| 浏览器隔离 | Edge 独立配置 `.runtime/opencli-edge-profile` |

扩展 manifest 已实读：Manifest V3，版本 `1.0.22`。`opencli doctor -v` 的
字面状态为：

```text
[OK] Daemon: running on port 19825 (v1.8.6)
[OK] Extension: connected (v1.0.22)
[OK] Connectivity: connected in 0.2s

Everything looks good!
```

命令退出状态：`0`。

## 基线行为

命令：

```powershell
git cat-file -e HEAD:scripts/manage-opencli-social-readonly.ps1
```

字面输出：

```text
fatal: path 'scripts/manage-opencli-social-readonly.ps1' exists on disk, but not in 'HEAD'
```

退出状态：`128`。

## 修改后行为

命令：

```powershell
pwsh -NoProfile -File scripts/manage-opencli-social-readonly.ps1 -Mode Plan -Platform douyin
```

字面输出：

```json
{
  "schema_version": "kjds-opencli-social-read-allowlist-v1",
  "platform": "douyin",
  "commands": [
    {"platform":"douyin","command":"whoami","domain":"creator.douyin.com","arguments":[],"access":"read","external_write":false},
    {"platform":"douyin","command":"profile","domain":"creator.douyin.com","arguments":[],"access":"read","external_write":false},
    {"platform":"douyin","command":"videos","domain":"creator.douyin.com","arguments":["--limit","20","--page","1","--status","all"],"access":"read","external_write":false}
  ],
  "deny_by_default": true,
  "output_root": ".runtime\\social-intelligence\\opencli"
}
```

退出状态：`0`。

## 真实只读采集

命令：

```powershell
pwsh -NoProfile -File scripts/manage-opencli-social-readonly.ps1 -Mode Collect -Platform douyin
```

字面结果摘要：

```text
run_id=20260804T102053Z-0a809506
status=pass
douyin.whoami exit_code=0 outcome=success external_write=false stdout_sha256=8144dc11d5616cc5d423803510da07fe4fe8e0db74456f904adcd30a9fc54d39
douyin.profile exit_code=0 outcome=success external_write=false stdout_sha256=173639de32de9b604c88954f715d28680b8674965468cc042602f7c65bc5217b
douyin.videos exit_code=0 outcome=success external_write=false stdout_sha256=a5338d955b09046ec0b16f3a9625b7955c763aae07dc722e474e6078745f932f
```

退出状态：`0`。本次账号聚合只读结果为：粉丝 `0`、关注 `93`、作品 `0`；
没有可继续调用 `stats` 的作品 ID。

小红书同一路径的首个 `whoami` 在 60 秒上游时限后返回：

```text
run_id=20260804T102123Z-6c461a9e
status=failed
xiaohongshu.whoami exit_code=75 outcome=failed external_write=false
error.code=TIMEOUT
error.message=xiaohongshu/whoami timed out after 60s
```

包装器退出状态：`1`。该平台没有继续执行后续命令，也没有形成采集数据。

## 合同测试

命令：

```powershell
uv run ruff check tests/test_opencli_social_readonly_contract.py
uv run python -m pytest tests/test_opencli_social_readonly_contract.py -q -p no:cacheprovider --basetemp .runtime/pytest-opencli-social-verification
git diff --check -- docs/project/registries/social_intelligence_read_allowlist.json scripts/manage-opencli-social-readonly.ps1 scripts/rollback-opencli-social-readonly.ps1 tests/test_opencli_social_readonly_contract.py
```

字面输出与退出状态：

```text
All checks passed!
.....                                                                    [100%]
5 passed in 0.06s
ruff_exit=0
pytest_exit=0
diff_check_exit=0
```

验证覆盖：精确 allowlist、默认拒绝、写命令/搜索/评论/下载隔离、固定版本与扩展摘要、
独立浏览器配置、运行时 access/domain 漂移检查、JSON 原文与 stderr 哈希、无任意命令透传、
回滚路径限定。

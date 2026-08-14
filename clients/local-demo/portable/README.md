# KJDS Local Demo v2（便携版）

## 运行

要求：Node.js 24 或更高版本。完整解压 ZIP 后，在本目录运行：

- PowerShell：`./start.ps1`
- Windows CMD：`start.cmd`
- 其他终端：`node launcher.mjs`

浏览器打开 `http://127.0.0.1:43195/#/dashboard`。启动器保持前台运行；按 `Ctrl+C` 停止。

## 固定边界

- 仅监听 `127.0.0.1:43195`，不监听局域网或公网地址。
- 仅允许 loopback Host、`GET` 和 `HEAD`。
- 不连接外网、不代理请求、不提供任何后端路由。
- `app/` 中只有构建后的合成数据静态 PWA，不含账号、Cookie、API Key、真实经营数据或源码。
- 页面持续显示 `LOCAL DEMO / 合成数据 / 不计费`。

## 重置与清理

- 页面内“重置场景”恢复 Scenario、State 与 Read Model 哈希。
- 命令行重置：`node reset.mjs`，然后重新运行启动命令。
- 完全清理运行时：`node cleanup.mjs`。

清理程序先向 loopback server 校验随机 challenge、PID 与包路径，只停止本包启动器，并仅删除本目录内 `.runtime/`。重复运行会返回 `already_clean`。

`PORTABLE_MANIFEST.json` 给出每个包内文件的 SHA-256、长度和权限；ZIP 外的同名 `.manifest.json` 给出 ZIP SHA-256。

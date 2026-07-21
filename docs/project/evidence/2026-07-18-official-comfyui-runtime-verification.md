# 官方 ComfyUI 与图片 Brief 前置闸门验证

| 项 | 值 |
|---|---|
| 日期 | 2026-07-18 |
| 状态 | PASS（执行器健康与 Brief 闸门）；真实 SKU 出图未执行 |
| 对应任务 | BAS-021 |
| 运行地址 | `http://127.0.0.1:8189`（仅 loopback） |
| ComfyUI | 官方 `Comfy-Org/ComfyUI`，`0.27.0` |
| GPU | NVIDIA GeForce RTX 4060 Laptop GPU |

## 决策

- 直接复用官方 [ComfyUI](https://github.com/Comfy-Org/ComfyUI) 作为本地图片执行器，不安装 ComfyUI-Manager，不把第三方 MCP 或 custom nodes 设为当前生产依赖。
- 启动基线使用 `--disable-all-custom-nodes`；KJDS 继续持有商品事实、七类图片 readiness、ContentAsset、Evidence、QA 和审批。
- 只允许三个受控模式：`retouch`、`composite`、`infographic`。Web 当前只能创建冻结 Brief，不会自动提交 workflow、生成图片或上架。
- 官方仓库采用 GPL-3.0；分发或改造场景必须重新做许可证评审。本次仅本地运行官方程序。

## 运行验证

本机已有官方仓库和独立虚拟环境，使用下列等价启动参数：

```text
python main.py --listen 127.0.0.1 --port 8189
  --disable-all-custom-nodes
  --extra-model-paths-config extra_model_paths.clean.yaml
```

验证结果：

```json
{
  "name": "comfyui",
  "status": "ok",
  "detail": "0.27.0 · cuda:0 NVIDIA GeForce RTX 4060 Laptop GPU : cudaMallocAsync"
}
```

已验证官方 `/system_stats` 与 `/features` 可访问，KJDS `ComfyUIProvider.healthcheck()` 能读取版本和设备。官方服务器合同参考：

- [Server communication overview](https://docs.comfy.org/development/comfyui-server/comms_overview)
- [Server routes](https://docs.comfy.org/development/comfyui-server/comms_routes)
- [ComfyUI license](https://github.com/Comfy-Org/ComfyUI/blob/master/LICENSE)

## 业务闸门验证

- 三类 Passport 已批准但七类图片 readiness 不完整：拒绝图片 Brief。
- 原图与权利证据不是 readiness 中的精确配对：拒绝图片 Brief。
- 只有 7/7 角色获批、所选原图与授权精确配对、且证据仍有效时，才建立 ContentAsset Brief。
- 建立 Brief 不调用 `/prompt`，因此不会绕过商品负责人、内容 QA 或 G2 审核。

## 可重复验证

```text
uv run ruff check .
uv run pytest -q
cd web
npm run build
```

结果：Ruff PASS；145 项测试 PASS（另有一条现有 Starlette/httpx 弃用警告）；Next.js 生产构建 PASS；`git diff --check` PASS。

## 未完成与边界

- 尚无三项真实候选 SKU，因此没有用真实商品、授权原图或真实工作流出图。
- 尚未固化针对 Ozon 的 workflow 模板、生成队列 worker、结果下载和 Evidence 自动捕获；这些必须在真实图片 Brief 通过后按单一受控模板增量实现。
- 当前运行健康不等于图片质量、俄语准确性、Ozon 合规或商业可售性已验证。

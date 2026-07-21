# API 镜像运行时资源一致性验证

| 项目 | 结果 |
|---|---|
| 日期 | 2026-07-18 |
| 范围 | BAS-029 / BR-018 |
| 首次镜像导入 | FAIL：缺少 `/app/docs/project/registries/loop_engineering_registry.json` |
| 修复后镜像导入 | PASS |
| 真实容器健康检查 | `GET /health/ready` → 200 |
| 完整 G-1 | PASS，`container_import=true` |

## 修复边界

- API 启动时读取 Loop Engineering registry；本地工作区此前存在该文件，但生产 Docker 镜像没有复制 `docs`，导致镜像内 `import apps.control_plane.api` 失败。
- Dockerfile 现在只复制这一份机器真源；`.dockerignore` 仍排除其他项目文档，不扩大运行镜像资料面。
- G-1 会构建生产 API 镜像，并在无数据库连接的导入阶段验证所有启动时 Python 模块及 registry 可加载。随后原有本地 API/PostgreSQL/Web smoke 继续运行。
- 本项不把私密启动资料、证据原件、测试目录或完整文档树放入镜像。

## 机器证据

- `.runtime/G1_VERIFICATION.json`
- 完成时间：`2026-07-18T11:31:04.1549410Z`
- 迁移：`20260718_0036`
- Python：152 passed；Web：6 passed；G-1 内密钥扫描 265 文件，证据文档同步后复扫当前 266 文件
- 隔离恢复 SHA-256：`229d5a154f7efbae834df62c049a5b1a7c4567393cb3c0144c37e10c0e0ec2da`
- 恢复计数：商品 4、订单 0、Evidence 19、只读运行 1

## 保留边界

该验证证明当前镜像包含已知启动时资源并能启动健康容器，不等于托管生产部署、镜像签名、SBOM、漏洞扫描或云环境网络与密钥配置已经完成。

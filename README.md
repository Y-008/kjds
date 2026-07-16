# KJDS — AI 跨境电商控制平面

这是面向俄罗斯市场的 AI 跨境电商经营系统。生产数据平台采用 Supabase PostgreSQL，本机 PostgreSQL 保留作开发和离线备用。系统当前覆盖：

- 市场原始观察、来源证据和可复算机会评分；
- Product / Compliance / Quality Passport；
- 图片、视频、文案 Brief，生成资产和五项 QA；
- 带预算封顶与止损线的增长实验；
- 订单费用账本和订单级 CM1 / CM2 / CM3；
- 高风险动作双人审批；
- 受模式和幂等约束的 Agent 任务；
- 稳定的领域事件与外部连接器协议。
- 1688、淘宝、天猫、京东、拼多多、Alibaba、AliExpress、Amazon、Temu、Shopify 和 WooCommerce 的统一供货连接器目录；
- 采购价、国内运费、国际物流、包装、关税、尾程、平台费、广告与退货准备金的单品 CM3 和保本价；
- 通过产品护照、正 CM3 和双人审批门禁生成 Ozon 上架草稿。

整体边界见 [架构说明](docs/architecture.md)，经营执行见 [90 天执行总纲](Ozon_90天执行总纲.md)。

## 当前目录

```text
apps/control_plane/
  api.py              HTTP API
  domain.py           稳定领域实体和状态
  repository.py       测试/开发存储适配器
  services.py         商品、订单、利润、审批、Agent
  intelligence.py     市场数据和机会评分
  content_growth.py   图片/视频/文案与增长实验
  connectors.py       Ozon/广告/物流/结算连接器协议
  sourcing.py         全球供货商品、物流利润和上架草稿规则
  source_connectors.py 平台能力目录
  sourcing_store.py   Supabase/PostgreSQL 持久化适配器
migrations/
  001_initial.sql     持久化模型与事务事件表
tests/
  test_core.py        核心业务约束测试
```

## Supabase 配置

1. 在 Supabase 新建项目，进入 **Connect**，复制 Session pooler 连接串（端口 5432）。
2. 复制 `.env.example` 为 `.env`。
3. 将连接串协议从 `postgres://` 改为 `postgresql+psycopg://`，并保留 `sslmode=require`。
4. 运行 `uv run alembic upgrade head`。

不要把 `.env`、数据库密码、Ozon API Key 或 service role key 发给 AI，也不要提交到 Git。

## 本地运行

```powershell
.\scripts\bootstrap.ps1
.\scripts\dev.ps1
```

打开 `http://127.0.0.1:8000/docs` 查看并调用接口。

也可以使用 Docker：

```powershell
docker compose up --build
```

## 测试

通过项目锁定环境执行：

```powershell
uv run ruff check .
uv run pytest
```

## 当前成熟度

数据库持久化、Ozon文件导入、工具健康检查、多供货平台标准化、物流利润核算和 Ozon 上架草稿已经接通。默认仍为14天影子模式，高风险写操作不会自动执行。真实平台采集需要对应账号/API权限；浏览器登录、验证码和付费授权必须由账号所有者完成。

环境规范见 [TOOLCHAIN.md](TOOLCHAIN.md)，环境决策见 [ADR-0001](docs/adr/ADR-0001-development-environment.md)。

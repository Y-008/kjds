# ADR-0003：Supabase 作为生产数据平台

- 状态：Accepted
- 日期：2026-07-13

## 决策

KJDS 生产数据库采用 Supabase PostgreSQL。本机 Docker PostgreSQL 只保留为开发、离线演练和灾难恢复验证环境。

- FastAPI 通过 SQLAlchemy/psycopg 使用 Supabase Session Pooler；
- Alembic 保持为唯一数据库结构迁移入口；
- 浏览器前端不持有数据库密码或 service role key，只调用 FastAPI；
- `public` schema 的业务表全部启用 RLS，未显式创建策略前不向 Data API 客户端开放；
- 商品图、视频、采集原始文件和网页快照后续进入私有 Supabase Storage bucket；
- 连接串、Ozon 密钥和 Firecrawl 登录凭据只存于 `.env` 或正式密钥系统；
- 核心财务事实仍由 KJDS 服务层校验，Supabase Edge Functions 不复制利润规则。

## 连接模式

当前 KJDS 是长驻 FastAPI 服务。如果运行网络支持 IPv6，可使用 Direct Connection；普通家庭/办公 IPv4 环境优先使用 Supavisor Session Pooler 端口 5432。Alembic 迁移也使用 session/direct 连接，不使用 transaction pooler。

## 后果

现有 PostgreSQL 领域模型、Decimal 精度和迁移无需重写，同时获得托管备份、Storage、Auth、Realtime 和远程管理能力。未来如果迁出 Supabase，核心业务仍可运行在标准 PostgreSQL。

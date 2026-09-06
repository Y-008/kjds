# PostgreSQL 合同测试数据库边界

媒体连接器、Primary Source Intake 和 TeamAgent evolution 的 PostgreSQL 合同测试会执行 Alembic 降级、升级、并发写入和触发器校验。这些测试具有破坏性，必须只对本次 G-1 运行创建并持有的临时数据库执行。

三个测试模块只读取 `KJDS_G1_CONTRACT_DATABASE_URL`。未设置该变量时，模块会被 pytest 明确跳过；`KJDS_DATABASE_URL` 是迁移管理员数据库或开发环境数据库，不能作为回退值。这样可以避免开发者 `.env` 中的共享 Hermes 数据库被生命周期回放改变，也避免在数据库已发生漂移时把原始 `UndefinedTable` 当成产品代码失败。

G-1 流程在创建并迁移运行范围内的合同数据库后设置 `KJDS_G1_CONTRACT_DATABASE_URL`，执行这些模块，再在清理阶段删除该变量并确认数据库归属。直接运行合同测试时，应显式提供一个同等隔离、可回收的临时 PostgreSQL URL；没有这样的 URL 时，跳过是预期结果。

测试仍会在迁移生命周期中临时把 `KJDS_DATABASE_URL` 指向同一个合同数据库，供 Alembic 的 `env.py` 读取；每个测试结束后恢复调用方环境变量。该临时重绑定不改变生产运行时的数据库权限边界。

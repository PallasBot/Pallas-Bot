-- 可选：诊断用扩展（非 Bot 启动硬依赖）。
-- 需具备 CREATE EXTENSION 权限；托管 PG 常需由实例管理员执行一次。
--
--   psql "$DATABASE_URL" -f deploy/pg/extensions.sql
--
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

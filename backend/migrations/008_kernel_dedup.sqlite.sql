-- 008 (SQLite only): unique dedup index on kernel events; MySQL got this
-- constraint from 004_enterprise.mysql.sql.
CREATE UNIQUE INDEX IF NOT EXISTS uq_kernel_dedup ON kernel_events (server_id, dedup_hash);

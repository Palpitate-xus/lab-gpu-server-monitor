-- 009 (MySQL only): widen fd_allocated; SQLite keeps the column as-is.
ALTER TABLE server_metrics MODIFY COLUMN fd_allocated BIGINT DEFAULT 0;

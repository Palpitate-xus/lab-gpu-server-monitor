-- Drop legacy columns (SQLite >= 3.35 / MySQL both support DROP COLUMN).
ALTER TABLE server_metrics DROP COLUMN gpu_cpus;
ALTER TABLE server_metrics DROP COLUMN top_processes;

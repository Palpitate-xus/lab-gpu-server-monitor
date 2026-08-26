-- 004 (SQLite variant): tables are created by create_all(); this variant only
-- backfills columns that older SQLite databases are missing.
ALTER TABLE server_metrics ADD COLUMN cpu_iowait FLOAT DEFAULT 0;
ALTER TABLE server_metrics ADD COLUMN boot_id VARCHAR(128) DEFAULT '';
ALTER TABLE server_metrics ADD COLUMN inodes JSON;
ALTER TABLE server_metrics ADD COLUMN sock_estab INT DEFAULT 0;
ALTER TABLE server_metrics ADD COLUMN sock_timewait INT DEFAULT 0;
ALTER TABLE server_metrics ADD COLUMN fd_allocated INT DEFAULT 0;
ALTER TABLE server_metrics ADD COLUMN fd_max INT DEFAULT 0;
ALTER TABLE server_metrics ADD COLUMN error_code VARCHAR(32) DEFAULT 'OK';
ALTER TABLE server_metrics ADD COLUMN ssh_latency FLOAT DEFAULT 0;
ALTER TABLE servers ADD COLUMN expected_gpu_count INT DEFAULT 0;

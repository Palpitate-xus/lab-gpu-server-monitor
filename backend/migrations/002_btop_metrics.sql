-- btop-grade metric columns (alert/rollup tables come from create_all).
-- Fresh databases already have these columns via create_all; tolerated errors skip them.
ALTER TABLE server_metrics ADD COLUMN cpu_model VARCHAR(255) NOT NULL DEFAULT '';
ALTER TABLE server_metrics ADD COLUMN cpu_freq_avg DOUBLE NOT NULL DEFAULT 0;
ALTER TABLE server_metrics ADD COLUMN cpu_temp_package DOUBLE NOT NULL DEFAULT 0;
ALTER TABLE server_metrics ADD COLUMN cores JSON NOT NULL;
ALTER TABLE server_metrics ADD COLUMN mem_available_mb DOUBLE NOT NULL DEFAULT 0;
ALTER TABLE server_metrics ADD COLUMN mem_cached_mb DOUBLE NOT NULL DEFAULT 0;
ALTER TABLE server_metrics ADD COLUMN disk_io JSON NOT NULL;
ALTER TABLE server_metrics ADD COLUMN net_ifaces JSON NOT NULL;
ALTER TABLE server_metrics ADD COLUMN processes JSON NOT NULL;
ALTER TABLE server_metrics ADD COLUMN users JSON NOT NULL;
ALTER TABLE server_metrics ADD COLUMN duration DOUBLE NOT NULL DEFAULT 0;

CREATE INDEX ix_server_metrics_server_time ON server_metrics (server_id, collected_at);

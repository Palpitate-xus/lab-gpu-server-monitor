-- btop-grade metric columns + data-retention policy change (history kept forever)
ALTER TABLE server_metrics ADD COLUMN cpu_model TEXT NOT NULL DEFAULT '';
ALTER TABLE server_metrics ADD COLUMN cpu_freq_avg REAL NOT NULL DEFAULT 0;
ALTER TABLE server_metrics ADD COLUMN cpu_temp_package REAL NOT NULL DEFAULT 0;
ALTER TABLE server_metrics ADD COLUMN cores JSON NOT NULL DEFAULT '[]';
ALTER TABLE server_metrics ADD COLUMN mem_available_mb REAL NOT NULL DEFAULT 0;
ALTER TABLE server_metrics ADD COLUMN mem_cached_mb REAL NOT NULL DEFAULT 0;
ALTER TABLE server_metrics ADD COLUMN disk_io JSON NOT NULL DEFAULT '[]';
ALTER TABLE server_metrics ADD COLUMN net_ifaces JSON NOT NULL DEFAULT '[]';
ALTER TABLE server_metrics ADD COLUMN processes JSON NOT NULL DEFAULT '[]';
ALTER TABLE server_metrics ADD COLUMN users JSON NOT NULL DEFAULT '[]';
ALTER TABLE server_metrics ADD COLUMN duration REAL NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS ix_server_metrics_server_time ON server_metrics (server_id, collected_at DESC);

CREATE TABLE IF NOT EXISTS alert_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    metric TEXT NOT NULL,
    op TEXT NOT NULL,
    threshold REAL NOT NULL,
    duration_minutes INTEGER NOT NULL DEFAULT 0,
    server_id INTEGER NULL REFERENCES servers(id) ON DELETE CASCADE,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS alert_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id INTEGER NULL REFERENCES alert_rules(id) ON DELETE SET NULL,
    server_id INTEGER NOT NULL,
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    threshold REAL NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    triggered_at TEXT NOT NULL DEFAULT (datetime('now')),
    recovered_at TEXT NULL,
    notified INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_alert_events_open ON alert_events (server_id, metric) WHERE recovered_at IS NULL;

CREATE TABLE IF NOT EXISTS metric_rollup_hourly (
    hour_ts TEXT NOT NULL,
    server_id INTEGER NOT NULL,
    avg_cpu REAL NOT NULL DEFAULT 0,
    max_cpu REAL NOT NULL DEFAULT 0,
    avg_mem_percent REAL NOT NULL DEFAULT 0,
    max_mem_percent REAL NOT NULL DEFAULT 0,
    avg_gpu_util REAL NOT NULL DEFAULT 0,
    max_gpu_util REAL NOT NULL DEFAULT 0,
    avg_gpu_temp REAL NOT NULL DEFAULT 0,
    max_gpu_temp REAL NOT NULL DEFAULT 0,
    avg_gpu_mem_percent REAL NOT NULL DEFAULT 0,
    max_gpu_mem_percent REAL NOT NULL DEFAULT 0,
    samples INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (hour_ts, server_id)
);

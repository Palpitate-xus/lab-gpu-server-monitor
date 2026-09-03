-- 015: composite indexes matching hot polling, detail, and detector queries
CREATE INDEX IF NOT EXISTS ix_server_metrics_server_time
    ON server_metrics (server_id, collected_at);
CREATE INDEX IF NOT EXISTS idx_inv_server
    ON host_inventory (server_id, collected_at);
CREATE INDEX IF NOT EXISTS idx_kernel_server
    ON kernel_events (server_id, collected_at);
CREATE INDEX IF NOT EXISTS idx_kernel_type
    ON kernel_events (event_type, collected_at);
CREATE INDEX IF NOT EXISTS idx_slow_server
    ON slow_health (server_id, collected_at);
CREATE INDEX IF NOT EXISTS idx_ipmi_server_time
    ON ipmi_snapshots (server_id, collected_at);
CREATE INDEX IF NOT EXISTS idx_note_server_time
    ON server_notes (server_id, ts);
CREATE INDEX IF NOT EXISTS idx_alert_open_time
    ON alert_events (recovered_at, triggered_at);
CREATE INDEX IF NOT EXISTS idx_alert_server_open
    ON alert_events (server_id, recovered_at, metric, rule_id);

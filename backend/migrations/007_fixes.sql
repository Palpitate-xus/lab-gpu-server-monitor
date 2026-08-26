-- 007: alert acknowledgement (ack != recover), detector ECC baseline,
-- server lifecycle status, alert assignee.
ALTER TABLE alert_events ADD COLUMN acked_at DATETIME NULL;
ALTER TABLE alert_events ADD COLUMN acked_by VARCHAR(64) DEFAULT '';
ALTER TABLE alert_events ADD COLUMN assignee VARCHAR(64) DEFAULT '';
ALTER TABLE gpu_baseline ADD COLUMN ecc_uncorrected_baseline INT NULL;
ALTER TABLE servers ADD COLUMN status VARCHAR(16) NOT NULL DEFAULT 'active';
ALTER TABLE servers ADD COLUMN status_reason TEXT;
ALTER TABLE servers ADD COLUMN status_until DATETIME NULL;

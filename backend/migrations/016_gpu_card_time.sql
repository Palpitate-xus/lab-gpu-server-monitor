-- Additive migration: preserve legacy aggregates until raw-data reconstruction.
ALTER TABLE server_metrics ADD COLUMN sample_interval_seconds INTEGER NULL;
ALTER TABLE server_metrics_hourly ADD COLUMN gpu_sample_minutes FLOAT NULL;
ALTER TABLE server_metrics_hourly ADD COLUMN idle_held_gpu_minutes FLOAT NULL;
ALTER TABLE server_metrics_hourly ADD COLUMN gpu_time_estimated BOOLEAN NOT NULL DEFAULT 1;

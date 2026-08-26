-- Drop legacy columns replaced by the new schema (SQLite >= 3.35 supports DROP COLUMN).
-- Tolerated silently if they don't exist or the SQLite is older (data stays, inserts work
-- because the new INSERT no longer references these columns... unless NOT NULL without
-- default -- in that case rebuild the table below as a fallback).
ALTER TABLE server_metrics DROP COLUMN gpu_cpus;
ALTER TABLE server_metrics DROP COLUMN top_processes;

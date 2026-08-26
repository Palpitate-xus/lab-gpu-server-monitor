-- Baseline settings seed (idempotent): key is the PK so IGNORE handles conflicts
-- on both MySQL (INSERT IGNORE) and SQLite (OR IGNORE -> INSERT syntax differs,
-- handled by the runner replacing the marker below).
INSERT IGNORE INTO settings (`key`, `value`) VALUES ('retention_days', '0');

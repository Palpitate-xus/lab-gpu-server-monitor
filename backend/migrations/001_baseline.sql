-- Fresh-install baseline marker (tables are created by SQLAlchemy create_all;
-- this migration only seeds the default retention policy: keep history forever).
INSERT OR IGNORE INTO settings (key, value) VALUES ('retention_days', '0');

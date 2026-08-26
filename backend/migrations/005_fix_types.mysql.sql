-- 005: fd_max exceeds INT range on hosts with huge fs.file-max
ALTER TABLE server_metrics MODIFY COLUMN fd_max BIGINT DEFAULT 0;

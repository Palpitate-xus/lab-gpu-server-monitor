-- 011: store derived instantaneous power per IPMI snapshot for energy math
ALTER TABLE ipmi_snapshots ADD COLUMN power_w FLOAT NOT NULL DEFAULT 0;

-- 010: out-of-band IPMI (BMC) support
ALTER TABLE servers ADD COLUMN bmc_host VARCHAR(255) NOT NULL DEFAULT '';
ALTER TABLE servers ADD COLUMN bmc_user VARCHAR(64) NOT NULL DEFAULT '';
ALTER TABLE servers ADD COLUMN bmc_password TEXT;

CREATE TABLE ipmi_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    server_id INTEGER NOT NULL,
    collected_at DATETIME NOT NULL,
    ok BOOLEAN NOT NULL DEFAULT 1,
    error TEXT,
    mc_info TEXT,
    chassis TEXT,
    power TEXT,
    sensors TEXT,
    sel TEXT,
    sel_info TEXT,
    fru TEXT,
    lan TEXT,
    duration FLOAT NOT NULL DEFAULT 0
);
CREATE INDEX ix_ipmi_snapshots_server ON ipmi_snapshots(server_id);
CREATE INDEX ix_ipmi_snapshots_time ON ipmi_snapshots(collected_at);

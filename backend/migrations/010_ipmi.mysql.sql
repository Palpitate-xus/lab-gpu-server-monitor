-- 010: out-of-band IPMI (BMC) support
ALTER TABLE servers ADD COLUMN bmc_host VARCHAR(255) NOT NULL DEFAULT '';
ALTER TABLE servers ADD COLUMN bmc_user VARCHAR(64) NOT NULL DEFAULT '';
ALTER TABLE servers ADD COLUMN bmc_password TEXT NULL;

CREATE TABLE ipmi_snapshots (
    id INT AUTO_INCREMENT PRIMARY KEY,
    server_id INT NOT NULL,
    collected_at DATETIME NOT NULL,
    ok TINYINT(1) NOT NULL DEFAULT 1,
    error TEXT NULL,
    mc_info JSON NULL,
    chassis JSON NULL,
    power JSON NULL,
    sensors JSON NULL,
    sel JSON NULL,
    sel_info JSON NULL,
    fru JSON NULL,
    lan JSON NULL,
    duration FLOAT NOT NULL DEFAULT 0,
    KEY ix_ipmi_snapshots_server (server_id),
    KEY ix_ipmi_snapshots_time (collected_at)
);

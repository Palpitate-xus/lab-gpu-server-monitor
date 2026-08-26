-- 004: enterprise monitoring tables
-- host inventory (daily), kernel events (XID/OOM/MCE/AER...), slow-tier
-- health snapshots (NVMe SMART / RAID / NFS / MIG / NVLink / IPMI),
-- GPU UUID baseline tracking, collector health per cycle.

CREATE TABLE IF NOT EXISTS host_inventory (
    id INT AUTO_INCREMENT PRIMARY KEY,
    server_id INT NOT NULL,
    collected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    machine_id VARCHAR(128) DEFAULT '',
    dmi JSON,
    lscpu JSON,
    numa JSON,
    gpu_topology TEXT,
    pci_numa JSON,
    disks JSON,
    nics JSON,
    ip_addrs JSON,
    ib JSON,
    time_info JSON,
    gpu_baseline JSON,
    INDEX idx_inv_server (server_id, collected_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS kernel_events (
    id INT AUTO_INCREMENT PRIMARY KEY,
    server_id INT NOT NULL,
    collected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    boot_id VARCHAR(128) DEFAULT '',
    event_type VARCHAR(64) NOT NULL,
    severity VARCHAR(16) DEFAULT 'info',
    gpu_uuid VARCHAR(64) DEFAULT '',
    xid INT DEFAULT 0,
    message TEXT,
    raw_message TEXT,
    dedup_hash VARCHAR(64) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_kernel_dedup (server_id, dedup_hash),
    INDEX idx_kernel_server (server_id, collected_at),
    INDEX idx_kernel_type (event_type, collected_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS slow_health (
    id INT AUTO_INCREMENT PRIMARY KEY,
    server_id INT NOT NULL,
    collected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    nvme_smart JSON,
    mdraid JSON,
    nfs_mounts JSON,
    systemd_failed JSON,
    services JSON,
    mig JSON,
    nvlink JSON,
    ipmi JSON,
    duration FLOAT DEFAULT 0,
    INDEX idx_slow_server (server_id, collected_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS gpu_baseline (
    id INT AUTO_INCREMENT PRIMARY KEY,
    server_id INT NOT NULL,
    gpu_uuid VARCHAR(64) NOT NULL,
    name VARCHAR(128) DEFAULT '',
    serial VARCHAR(128) DEFAULT '',
    pci_bus_id VARCHAR(32) DEFAULT '',
    first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    missing_since DATETIME DEFAULT NULL,
    UNIQUE KEY uq_gpu_baseline (server_id, gpu_uuid)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- fast-tier additions on server_metrics
ALTER TABLE server_metrics ADD COLUMN cpu_iowait FLOAT DEFAULT 0;
ALTER TABLE server_metrics ADD COLUMN boot_id VARCHAR(128) DEFAULT '';
ALTER TABLE server_metrics ADD COLUMN inodes JSON;
ALTER TABLE server_metrics ADD COLUMN sock_estab INT DEFAULT 0;
ALTER TABLE server_metrics ADD COLUMN sock_timewait INT DEFAULT 0;
ALTER TABLE server_metrics ADD COLUMN fd_allocated INT DEFAULT 0;
ALTER TABLE server_metrics ADD COLUMN fd_max INT DEFAULT 0;
ALTER TABLE server_metrics ADD COLUMN error_code VARCHAR(32) DEFAULT 'OK';
ALTER TABLE server_metrics ADD COLUMN ssh_latency FLOAT DEFAULT 0;

-- servers: expected GPU baseline hint (set from first successful collect when empty)
ALTER TABLE servers ADD COLUMN expected_gpu_count INT DEFAULT 0;

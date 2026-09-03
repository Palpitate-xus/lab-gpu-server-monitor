-- 014: keep the large host process list once per server instead of per history row
CREATE TABLE IF NOT EXISTS server_process_snapshots (
    server_id INTEGER NOT NULL PRIMARY KEY,
    collected_at DATETIME NOT NULL,
    processes JSON,
    FOREIGN KEY (server_id) REFERENCES servers(id) ON DELETE CASCADE
);

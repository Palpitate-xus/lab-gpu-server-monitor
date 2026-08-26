-- 006: server type (gpu | cpu) so CPU-only boxes can skip GPU UI/cards
ALTER TABLE servers ADD COLUMN server_type VARCHAR(8) NOT NULL DEFAULT 'gpu';

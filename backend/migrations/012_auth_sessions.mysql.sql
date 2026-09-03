ALTER TABLE users ADD COLUMN auth_id VARCHAR(64) NULL;
UPDATE users SET auth_id = REPLACE(UUID(), '-', '') WHERE auth_id IS NULL OR auth_id = '';
ALTER TABLE users MODIFY auth_id VARCHAR(64) NOT NULL;
CREATE UNIQUE INDEX uq_users_auth_id ON users(auth_id);
ALTER TABLE users ADD COLUMN token_version INT NOT NULL DEFAULT 1;

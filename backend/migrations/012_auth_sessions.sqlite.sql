ALTER TABLE users ADD COLUMN auth_id VARCHAR(64) NOT NULL DEFAULT '';
UPDATE users
SET auth_id = lower(hex(randomblob(16))) || lower(hex(randomblob(8)))
WHERE auth_id = '';
CREATE UNIQUE INDEX uq_users_auth_id ON users(auth_id);
ALTER TABLE users ADD COLUMN token_version INTEGER NOT NULL DEFAULT 1;

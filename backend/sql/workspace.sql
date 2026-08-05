PRAGMA foreign_keys = ON;
PRAGMA synchronous = NORMAL;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS users (
  user_id TEXT PRIMARY KEY,
  email TEXT UNIQUE,
  name TEXT,
  avatar_url TEXT,
  provider TEXT NOT NULL,
  provider_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workspace_members (
  workspace_id TEXT NOT NULL REFERENCES workspaces(workspace_id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK(role IN ('owner','teacher','student','viewer')),
  joined_at TEXT NOT NULL,
  PRIMARY KEY (workspace_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_workspace_member_user ON workspace_members(user_id);
CREATE INDEX IF NOT EXISTS idx_workspace_member_workspace ON workspace_members(workspace_id);

-- One-time-fetch OAuth credential for the optional Google Drive import
-- integration. Only ever used to list/download files at import time; imported
-- files then live in the local workspace like any other local file.
-- No FK to users(user_id): this must also work in local/no-auth mode, where
-- the "local_admin" identity is synthetic and never persisted as a real row.
CREATE TABLE IF NOT EXISTS google_drive_credentials (
  user_id       TEXT PRIMARY KEY,
  access_token  TEXT NOT NULL,
  refresh_token TEXT,
  expires_at    TEXT,
  scope         TEXT,
  updated_at    TEXT NOT NULL
);

-- Goose-inspired session/thread persistence for JARVIS debate pipeline
CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS threads (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL,
  agent_name TEXT NOT NULL,
  created_at REAL NOT NULL,
  FOREIGN KEY(session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS thread_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id INTEGER NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  agent_visible INTEGER NOT NULL DEFAULT 1,
  user_visible INTEGER NOT NULL DEFAULT 1,
  created_at REAL NOT NULL,
  FOREIGN KEY(thread_id) REFERENCES threads(id)
);

CREATE INDEX IF NOT EXISTS idx_threads_session ON threads(session_id);
CREATE INDEX IF NOT EXISTS idx_thread_messages_thread ON thread_messages(thread_id);

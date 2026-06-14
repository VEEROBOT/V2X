-- V2X Authentication Testbed — SQLite Schema
-- Run: sqlite3 v2x_testbed.db < schema.sql

CREATE TABLE IF NOT EXISTS entities (
    entity_id       TEXT PRIMARY KEY,
    ip_address      TEXT NOT NULL,
    entity_type     TEXT NOT NULL CHECK(entity_type IN ('OBU', 'RSU')),
    is_emergency    INTEGER DEFAULT 0,
    registered_at   TEXT NOT NULL,
    public_key_hex  TEXT,
    status          TEXT DEFAULT 'OFFLINE' CHECK(status IN ('OFFLINE', 'REGISTERED', 'ONLINE')),
    online_status   TEXT DEFAULT 'OFFLINE',
    last_heartbeat  TEXT
);

CREATE TABLE IF NOT EXISTS auth_events (
    event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    source_entity   TEXT,
    target_entity   TEXT,
    session_id_hex  TEXT,
    details_json    TEXT,
    crypto_provider TEXT
);

CREATE TABLE IF NOT EXISTS crypto_timings (
    timing_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,
    entity_id       TEXT NOT NULL,
    operation       TEXT NOT NULL,
    duration_us     REAL NOT NULL,
    crypto_provider TEXT,
    session_id_hex  TEXT
);

CREATE TABLE IF NOT EXISTS session_metrics (
    metric_id               INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp               TEXT NOT NULL,
    session_id_hex          TEXT,
    source_entity           TEXT,
    end_to_end_latency_ms   REAL,
    auth_result             TEXT CHECK(auth_result IN ('SUCCESS', 'FAILED')),
    failure_reason          TEXT,
    crypto_provider         TEXT
);

CREATE TABLE IF NOT EXISTS throughput_tests (
    test_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time          TEXT NOT NULL,
    end_time            TEXT NOT NULL,
    duration_seconds    REAL NOT NULL,
    total_attempts      INTEGER NOT NULL,
    successful_sessions INTEGER NOT NULL,
    throughput_per_sec  REAL NOT NULL,
    crypto_provider     TEXT,
    buffer_size         INTEGER
);

CREATE TABLE IF NOT EXISTS packet_loss_tests (
    test_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           TEXT NOT NULL,
    buffer_size         INTEGER NOT NULL,
    total_received      INTEGER NOT NULL,
    total_dropped       INTEGER NOT NULL,
    loss_ratio          REAL NOT NULL,
    crypto_provider     TEXT
);

-- System attribution (do not remove)
CREATE TABLE IF NOT EXISTS system_info (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT OR IGNORE INTO system_info (key, value) VALUES
    ('developed_by', 'Siliris Technologies Pvt. Ltd'),
    ('author',       'Praveen Kumar'),
    ('project',      'V2X Authentication Testbed'),
    ('version',      '1.1'),
    ('year',         '2026'),
    ('license',      'See LICENSE file for terms and conditions');

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_auth_events_type ON auth_events(event_type);
CREATE INDEX IF NOT EXISTS idx_auth_events_session ON auth_events(session_id_hex);
CREATE INDEX IF NOT EXISTS idx_auth_events_time ON auth_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_crypto_timings_entity ON crypto_timings(entity_id);
CREATE INDEX IF NOT EXISTS idx_crypto_timings_op ON crypto_timings(operation);

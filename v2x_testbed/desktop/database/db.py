"""
File: db.py
Module: V2X Authentication Testbed — Database

Purpose:
    Handles all SQLite database operations including schema initialization,
    entity registration, key storage, session tracking, and audit logging.

Author(s): Praveen Kumar
Company: Siliris Technologies Pvt. Ltd
Created: 15th February 2026
Version: 1.1

Key Responsibilities:
    - Database initialization and schema setup
    - Entity (OBU/RSU) registration management
    - Cryptographic key storage and retrieval
    - Session lifecycle tracking
    - Audit event logging

License:
    Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
    Proprietary - See LICENSE file for terms and conditions.
"""

import sqlite3
import os
import json
from datetime import datetime, timezone


class Database:
    def __init__(self, db_path):
        self.db_path = db_path
        self._ensure_dir()
        self._init_schema()

    def _ensure_dir(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

    def _init_schema(self):
        schema_path = os.path.join(os.path.dirname(self.db_path), "schema.sql")
        if not os.path.exists(schema_path):
            print(f"[DB] WARNING: schema.sql not found at {schema_path}")
            return

        conn = sqlite3.connect(self.db_path)
        with open(schema_path, "r") as f:
            conn.executescript(f.read())
        conn.close()
        print(f"[DB] Database initialized at {self.db_path}")

    def _connect(self):
        return sqlite3.connect(self.db_path)

    # =========================================================================
    # ENTITY OPERATIONS
    # =========================================================================

    def register_entity(self, entity_id, ip_address, entity_type,
                        is_emergency=False, public_key_hex=""):
        conn = self._connect()
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """INSERT OR REPLACE INTO entities
               (entity_id, ip_address, entity_type, is_emergency,
                registered_at, public_key_hex, status)
               VALUES (?, ?, ?, ?, ?, ?, 'REGISTERED')""",
            (entity_id, ip_address, entity_type, int(is_emergency),
             now, public_key_hex)
        )
        conn.commit()
        conn.close()

    def update_entity_status(self, entity_id, status):
        conn = self._connect()
        conn.execute(
            "UPDATE entities SET status = ? WHERE entity_id = ?",
            (status, entity_id)
        )
        conn.commit()
        conn.close()

    def get_all_entities(self):
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM entities ORDER BY entity_id").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_entity(self, entity_id):
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM entities WHERE entity_id = ?", (entity_id,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    # =========================================================================
    # AUTH EVENT OPERATIONS
    # =========================================================================

    def insert_auth_event(self, event):
        conn = self._connect()
        conn.execute(
            """INSERT INTO auth_events
               (timestamp, event_type, source_entity, target_entity,
                session_id_hex, details_json, crypto_provider)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                event.get("timestamp", datetime.now(timezone.utc).isoformat()),
                event["event_type"],
                event.get("source"),
                event.get("target"),
                event.get("session_id"),
                json.dumps(event.get("details", {})),
                event.get("crypto_provider", "placeholder"),
            )
        )
        conn.commit()
        conn.close()

    def get_recent_events(self, limit=50):
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT * FROM auth_events
               ORDER BY event_id DESC LIMIT ?""",
            (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # =========================================================================
    # CRYPTO TIMING OPERATIONS
    # =========================================================================

    def insert_crypto_timing(self, timing):
        conn = self._connect()
        conn.execute(
            """INSERT INTO crypto_timings
               (timestamp, entity_id, operation, duration_us,
                crypto_provider, session_id_hex)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                timing.get("timestamp", datetime.now(timezone.utc).isoformat()),
                timing["entity_id"],
                timing["operation"],
                timing["duration_us"],
                timing.get("crypto_provider", "placeholder"),
                timing.get("session_id"),
            )
        )
        conn.commit()
        conn.close()

    def get_crypto_timings(self, entity_id=None, limit=100):
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        if entity_id:
            rows = conn.execute(
                """SELECT * FROM crypto_timings
                   WHERE entity_id = ? ORDER BY timing_id DESC LIMIT ?""",
                (entity_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM crypto_timings ORDER BY timing_id DESC LIMIT ?",
                (limit,)
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # =========================================================================
    # SESSION METRICS
    # =========================================================================

    def insert_session_metric(self, metric):
        conn = self._connect()
        conn.execute(
            """INSERT INTO session_metrics
               (timestamp, session_id_hex, source_entity,
                end_to_end_latency_ms, auth_result, failure_reason,
                crypto_provider)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                metric.get("timestamp", datetime.now(timezone.utc).isoformat()),
                metric.get("session_id"),
                metric.get("source_entity"),
                metric.get("end_to_end_latency_ms"),
                metric.get("auth_result"),
                metric.get("failure_reason"),
                metric.get("crypto_provider", "placeholder"),
            )
        )
        conn.commit()
        conn.close()

    # =========================================================================
    # EXPORT
    # =========================================================================

    def export_table_csv(self, table_name):
        """Export any table as CSV string."""
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(f"SELECT * FROM {table_name}").fetchall()
        conn.close()

        if not rows:
            return ""

        headers = rows[0].keys()
        lines = [",".join(headers)]
        for row in rows:
            lines.append(",".join(str(row[h]) for h in headers))
        return "\n".join(lines)

    # =========================================================================
    # STATS (for dashboard)
    # =========================================================================

    def get_stats(self):
        conn = self._connect()
        stats = {}

        stats["total_entities"] = conn.execute(
            "SELECT COUNT(*) FROM entities"
        ).fetchone()[0]

        stats["registered_entities"] = conn.execute(
            "SELECT COUNT(*) FROM entities WHERE status = 'REGISTERED'"
        ).fetchone()[0]

        stats["total_auth_events"] = conn.execute(
            "SELECT COUNT(*) FROM auth_events"
        ).fetchone()[0]

        stats["successful_sessions"] = conn.execute(
            "SELECT COUNT(*) FROM auth_events WHERE event_type = 'SESSION_ESTABLISHED'"
        ).fetchone()[0]

        stats["failed_sessions"] = conn.execute(
            """SELECT COUNT(*) FROM auth_events WHERE event_type IN (
                'KC1_VERIFY_FAIL', 'POST_AUTH_HMAC_FAIL', 'POST_AUTH_DECRYPT_FAIL'
            )"""
        ).fetchone()[0]
        stats["replay_detected"] = conn.execute(
            "SELECT COUNT(*) FROM auth_events WHERE event_type = 'REPLAY_DETECTED'"
        ).fetchone()[0]

        stats["signature_failures"] = conn.execute(
            "SELECT COUNT(*) FROM auth_events WHERE event_type = 'SIGNATURE_CHECK_FAIL'"
        ).fetchone()[0]

        stats["timestamp_failures"] = conn.execute(
            "SELECT COUNT(*) FROM auth_events WHERE event_type = 'TIMESTAMP_CHECK_FAIL'"
        ).fetchone()[0]

        # Average latency
        row = conn.execute(
            "SELECT AVG(end_to_end_latency_ms) FROM session_metrics WHERE auth_result = 'SUCCESS'"
        ).fetchone()
        stats["avg_latency_ms"] = round(row[0], 3) if row and row[0] else 0

        conn.close()
        return stats

    # =========================================================================
    # PERFORMANCE METRICS (Week 5-6)
    # =========================================================================

    def get_timing_summary(self):
        """Aggregated crypto timing: avg/min/max per operation."""
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT operation,
                      COUNT(*) as count,
                      ROUND(AVG(duration_us), 1) as avg_us,
                      ROUND(MIN(duration_us), 1) as min_us,
                      ROUND(MAX(duration_us), 1) as max_us,
                      crypto_provider
               FROM crypto_timings
               GROUP BY operation, crypto_provider
               ORDER BY avg_us DESC"""
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_session_history(self, limit=500):
        """Session metrics for latency chart."""
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """SELECT metric_id, timestamp, session_id_hex, source_entity,
                      end_to_end_latency_ms, auth_result, failure_reason,
                      crypto_provider
               FROM session_metrics
               ORDER BY metric_id DESC LIMIT ?""",
            (limit,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_buffer_stats(self):
        """Packet loss test results."""
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM packet_loss_tests ORDER BY test_id DESC LIMIT 20"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def insert_packet_loss(self, data):
        """Insert a packet loss test result."""
        conn = self._connect()
        conn.execute(
            """INSERT INTO packet_loss_tests
               (timestamp, buffer_size, total_received, total_dropped,
                loss_ratio, crypto_provider)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                data.get("timestamp", datetime.now(timezone.utc).isoformat()),
                data["buffer_size"],
                data["total_received"],
                data["total_dropped"],
                data["loss_ratio"],
                data.get("crypto_provider", "placeholder"),
            )
        )
        conn.commit()
        conn.close()

    def insert_throughput(self, data):
        """Insert a throughput test result."""
        conn = self._connect()
        conn.execute(
            """INSERT INTO throughput_tests
               (start_time, end_time, duration_seconds, total_attempts,
                successful_sessions, throughput_per_sec, crypto_provider, buffer_size)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data["start_time"],
                data["end_time"],
                data["duration_seconds"],
                data["total_attempts"],
                data["successful_sessions"],
                data["throughput_per_sec"],
                data.get("crypto_provider", "placeholder"),
                data.get("buffer_size", 50),
            )
        )
        conn.commit()
        conn.close()

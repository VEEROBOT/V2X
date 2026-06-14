"""
File: log_receiver.py
Module: V2X Authentication Testbed — Log Receiver

Purpose:
    TCP server receiving and processing audit logs from RSU and OBU entities.
    Persists events to database and broadcasts to dashboard via callback.

Author(s): Praveen Kumar
Company: Siliris Technologies Pvt. Ltd
Created: 15th February 2026
Version: 1.1

Key Responsibilities:
    - Listen for incoming log messages on TCP:9000
    - Parse authentication events and session updates
    - Store events in audit log table
    - Notify dashboard of events via callback
    - Handle multiple concurrent connections

Protocol: Length-prefixed JSON messages
  [length: 4 bytes big-endian] [JSON payload: N bytes]

RSU connects to Desktop:9000 and sends events continuously.

License:
    Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
    Proprietary - See LICENSE file for terms and conditions.
"""

import socket
import struct
import threading
import json
import time
from datetime import datetime, timezone

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config
from database.db import Database


class LogReceiver:
    """TCP server that receives log events and stores in database."""

    def __init__(self, db, on_event_callback=None):
        self.db = db
        self.running = False
        self.on_event = on_event_callback  # Called for each event (for WebSocket push)
        self.connected_clients = []

    def _recv_exact(self, sock, n):
        """Receive exactly n bytes."""
        data = b""
        while len(data) < n:
            chunk = sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("Connection closed")
            data += chunk
        return data

    def _handle_client(self, client_sock, client_addr):
        """Handle a connected log sender (RSU or OBU)."""
        sender_id = f"{client_addr[0]}:{client_addr[1]}"
        self.connected_clients.append(sender_id)
        print(f"[LOG] Log sender connected: {sender_id}")

        try:
            while self.running:
                # Read length prefix (4 bytes, big-endian)
                try:
                    len_data = self._recv_exact(client_sock, 4)
                except ConnectionError:
                    break

                msg_len = struct.unpack("!I", len_data)[0]

                if msg_len > 65536:  # Sanity check: max 64KB per message
                    print(f"[LOG] WARNING: Message too large ({msg_len} bytes), skipping")
                    continue

                # Read JSON payload
                json_data = self._recv_exact(client_sock, msg_len)

                try:
                    event = json.loads(json_data.decode("utf-8"))
                except json.JSONDecodeError as e:
                    print(f"[LOG] WARNING: Invalid JSON from {sender_id}: {e}")
                    continue

                # Process the event
                self._process_event(event)

        except ConnectionError:
            print(f"[LOG] Log sender disconnected: {sender_id}")
        except Exception as e:
            print(f"[LOG] ERROR from {sender_id}: {e}")
        finally:
            client_sock.close()
            if sender_id in self.connected_clients:
                self.connected_clients.remove(sender_id)

    def _process_event(self, event):
        """Process a received event: store in DB and notify dashboard."""
        event_type = event.get("event_type", "UNKNOWN")
        source = event.get("source", "?")
        ts = event.get("timestamp", datetime.now(timezone.utc).isoformat())

        # Store in database
        self.db.insert_auth_event(event)

        # Store crypto timings if present
        crypto_timing = event.get("crypto_timing")
        if crypto_timing:
            for op_name, duration in crypto_timing.items():
                if isinstance(duration, (int, float)):
                    self.db.insert_crypto_timing({
                        "timestamp": ts,
                        "entity_id": source,
                        "operation": op_name,
                        "duration_us": duration * 1000,  # ms to μs
                        "crypto_provider": event.get("crypto_provider", "placeholder"),
                        "session_id": event.get("session_id"),
                    })

        # Record session metric on SESSION_ESTABLISHED
        if event_type == "SESSION_ESTABLISHED":
            details = event.get("details", {})
            if isinstance(details, str):
                try:
                    details = json.loads(details)
                except:
                    details = {}
            latency = details.get("total_latency_ms", 0)
            self.db.insert_session_metric({
                "timestamp": ts,
                "session_id": event.get("session_id"),
                "source_entity": source,
                "end_to_end_latency_ms": latency,
                "auth_result": "SUCCESS",
                "failure_reason": None,
                "crypto_provider": event.get("crypto_provider", "placeholder"),
            })

        # Record failed session metrics
        if event_type in ("SIGNATURE_CHECK_FAIL", "TIMESTAMP_CHECK_FAIL", "REPLAY_DETECTED", "KC1_VERIFY_FAIL"):
            self.db.insert_session_metric({
                "timestamp": ts,
                "session_id": event.get("session_id"),
                "source_entity": source,
                "end_to_end_latency_ms": None,
                "auth_result": "FAILED",
                "failure_reason": event_type,
                "crypto_provider": event.get("crypto_provider", "placeholder"),
            })

        # Record buffer stats for packet loss measurement
        if event_type == "BUFFER_STATS":
            details = event.get("details", {})
            if isinstance(details, str):
                try:
                    details = json.loads(details)
                except:
                    details = {}
            try:
                self.db.insert_packet_loss({
                    "timestamp": ts,
                    "buffer_size": details.get("buffer_size", 0),
                    "total_received": details.get("total_received", 0),
                    "total_dropped": details.get("total_dropped", 0),
                    "loss_ratio": details.get("loss_ratio", 0),
                    "crypto_provider": event.get("crypto_provider", "placeholder"),
                })
            except Exception as e:
                print(f"[LOG] WARNING: Failed to record buffer stats: {e}")

        # Log to console
        print(f"[LOG] {ts} | {event_type:30s} | {source}")

        # Notify dashboard (WebSocket push)
        if self.on_event:
            self.on_event(event)

    def start(self):
        """Start the log receiver server."""
        self.running = True

        self.thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.thread.start()
        print(f"[LOG] Log receiver started on port {config.LOG_RECEIVER_PORT}")

    def _listen_loop(self):
        """Listen for log sender connections."""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.settimeout(1.0)
        server.bind((config.DESKTOP_IP, config.LOG_RECEIVER_PORT))
        server.listen(5)

        while self.running:
            try:
                client_sock, client_addr = server.accept()
                t = threading.Thread(
                    target=self._handle_client,
                    args=(client_sock, client_addr),
                    daemon=True
                )
                t.start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"[LOG] Accept error: {e}")

        server.close()

    def stop(self):
        self.running = False
        print("[LOG] Log receiver stopping...")


# =============================================================================
# STANDALONE TEST
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("V2X Log Receiver — Standalone Mode")
    print("=" * 60)

    db = Database(config.DB_PATH)
    receiver = LogReceiver(db)
    receiver.start()

    print(f"  Listening on port {config.LOG_RECEIVER_PORT}")
    print("  Waiting for log senders... (Ctrl+C to stop)")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        receiver.stop()

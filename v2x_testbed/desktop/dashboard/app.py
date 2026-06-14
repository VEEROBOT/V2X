"""
File: app.py
Module: V2X Authentication Testbed — Dashboard

Purpose:
    Flask web application providing real-time monitoring of V2X authentication
    events and session management through WebSocket-based live event streaming
    and REST API endpoints.

Author(s): Praveen Kumar
Company: Siliris Technologies Pvt. Ltd
Created: 15th February 2026
Version: 1.1

Key Features:
    - Real-time event streaming via WebSocket
    - REST API for statistics and data export
    - Entity registration status tracking
    - Session lifecycle monitoring
    - Audit log visualization

License:
    Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
    Proprietary - See LICENSE file for terms and conditions.
"""

from flask import Flask, render_template, jsonify, Response, request
from flask_socketio import SocketIO
import json
import logging
import threading
import time

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config
from database.db import Database


app = Flask(__name__)
app.config["SECRET_KEY"] = "v2x-testbed-dashboard"
socketio = SocketIO(app, cors_allowed_origins="*")

# Suppress Flask/Werkzeug request logging (the annoying GET /api/stats lines)
log = logging.getLogger("werkzeug")
log.setLevel(logging.WARNING)

# Database instance (initialized in start_dashboard)
db = None


def push_event(event):
    """Push an auth event to connected browsers via WebSocket."""
    socketio.emit("auth_event", event)


# =============================================================================
# ROUTES
# =============================================================================

@app.route("/")
def index():
    """Main dashboard page."""
    entities = db.get_all_entities()
    stats = db.get_stats()
    return render_template("index.html", entities=entities, stats=stats)


@app.route("/api/entities")
def api_entities():
    """JSON API: all registered entities."""
    return jsonify(db.get_all_entities())


@app.route("/api/events")
def api_events():
    """JSON API: recent auth events."""
    return jsonify(db.get_recent_events(limit=100))


@app.route("/api/stats")
def api_stats():
    """JSON API: system statistics."""
    return jsonify(db.get_stats())


@app.route("/api/timings")
def api_timings():
    """JSON API: crypto operation timings."""
    return jsonify(db.get_crypto_timings(limit=200))


@app.route("/api/timing_summary")
def api_timing_summary():
    """JSON API: aggregated crypto timing stats per operation."""
    return jsonify(db.get_timing_summary())


@app.route("/api/session_history")
def api_session_history():
    """JSON API: session metrics for latency chart."""
    return jsonify(db.get_session_history(limit=500))


@app.route("/api/buffer_stats")
def api_buffer_stats():
    """JSON API: packet loss test results."""
    return jsonify(db.get_buffer_stats())


@app.route("/api/entity_status", methods=["POST"])
def api_entity_status():
    """Called by v2x_bridge heartbeat and v2x_obu_trigger to report ONLINE/OFFLINE."""
    data = request.get_json(force=True, silent=True) or {}
    entity_id = data.get("entity_id", "").strip()
    status    = data.get("status", "OFFLINE")
    if not entity_id or status not in ("ONLINE", "OFFLINE"):
        return jsonify({"error": "invalid"}), 400
    entity = db.set_entity_online_status(entity_id, status)
    if entity:
        socketio.emit("entity_status_changed", entity)
    return jsonify({"ok": True})


@app.route("/export/<table_name>")
def export_csv(table_name):
    """Download a table as CSV."""
    allowed_tables = [
        "entities", "auth_events", "crypto_timings",
        "session_metrics", "throughput_tests", "packet_loss_tests"
    ]
    if table_name not in allowed_tables:
        return "Invalid table name", 400

    csv_data = db.export_table_csv(table_name)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment;filename={table_name}.csv"}
    )


# =============================================================================
# WEBSOCKET EVENTS
# =============================================================================

@socketio.on("connect")
def handle_connect():
    print("[DASH] Browser connected")
    # Send current state
    socketio.emit("initial_state", {
        "entities": db.get_all_entities(),
        "stats": db.get_stats(),
        "recent_events": db.get_recent_events(limit=20),
    })


# =============================================================================
# START
# =============================================================================

def _watchdog_loop():
    """Mark entities OFFLINE when their heartbeat goes silent (battery death, crash, etc.)."""
    while True:
        time.sleep(20)
        try:
            stale = db.get_stale_online_entities(timeout_seconds=30)
            for entity in stale:
                updated = db.set_entity_online_status(entity["entity_id"], "OFFLINE")
                if updated:
                    socketio.emit("entity_status_changed", updated)
                    print(f"[DASH] {entity['entity_id']} heartbeat lost — marked OFFLINE")
        except Exception:
            pass


def start_dashboard(database):
    """Start the dashboard web server."""
    global db
    db = database
    threading.Thread(target=_watchdog_loop, daemon=True, name="watchdog").start()
    print(f"[DASH] Dashboard starting on http://localhost:{config.DASHBOARD_PORT}")
    socketio.run(app, host="0.0.0.0", port=config.DASHBOARD_PORT,
                 allow_unsafe_werkzeug=True, log_output=False)

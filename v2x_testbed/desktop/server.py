#!/usr/bin/env python3
"""
File: server.py
Module: V2X Authentication Testbed — Desktop Server

Purpose:
    Main entry point for the desktop server. Orchestrates and starts all
    desktop services including registration server, log receiver, and the
    real-time monitoring dashboard.

Author(s): Praveen Kumar
Company: Siliris Technologies Pvt. Ltd
Created: 15th February 2026
Version: 1.1

Key Services Started:
    1. Registration Server - TCP:8001 (OBU registration), TCP:8002 (RSU registration)
    2. Log Receiver - TCP:9000 (receives audit logs from RSU/OBU)
    3. Dashboard - HTTP:5000 with WebSocket (real-time monitoring UI)
    4. Database - SQLite for persistent storage

Usage:
    python3 server.py

License:
    Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
    Proprietary - See LICENSE file for terms and conditions.
"""

import sys
import os
import signal
import time
import threading

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

import config
from database.db import Database
from registration.reg_server import RegistrationServer
from log_service.log_receiver import LogReceiver
from dashboard.app import start_dashboard, push_event


def main():
    print("=" * 60)
    print("  V2X Authentication Testbed — Desktop Server")
    print("=" * 60)
    print()
    print(f"  Crypto provider: {config.CRYPTO_PROVIDER}")
    print(f"  Database:        {config.DB_PATH}")
    print()

    # Initialize database
    db = Database(config.DB_PATH)
    print()

    # Start registration servers
    reg_server = RegistrationServer(db)
    reg_server.start()
    print(f"  OBU registration: port {config.REG_PORT_OBU}")
    print(f"  RSU registration: port {config.REG_PORT_RSU}")
    print()

    # Start log receiver (with callback to push events to dashboard)
    log_receiver = LogReceiver(db, on_event_callback=push_event)
    log_receiver.start()
    print(f"  Log receiver:     port {config.LOG_RECEIVER_PORT}")
    print()

    # Handle Ctrl+C gracefully
    def shutdown(sig, frame):
        print("\n\nShutting down...")
        reg_server.stop()
        log_receiver.stop()
        print("Goodbye.")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Start dashboard (this blocks — runs Flask server)
    print(f"  Dashboard:        http://localhost:{config.DASHBOARD_PORT}")
    print()
    print("=" * 60)
    print("  All services running. Open dashboard in browser.")
    print("  Press Ctrl+C to stop.")
    print("=" * 60)
    print()

    start_dashboard(db)


if __name__ == "__main__":
    main()

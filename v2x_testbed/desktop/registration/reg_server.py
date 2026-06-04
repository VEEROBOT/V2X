"""
File: reg_server.py
Module: V2X Authentication Testbed — Registration Server

Purpose:
    TCP server managing one-time cryptographic key provisioning for all
    entities (OBU and RSU). Implements the LLD Section 3.4 registration
    protocol with message-based communication.

Author(s): Praveen Kumar
Company: Siliris Technologies Pvt. Ltd
Created: 15th February 2026
Version: 1.1

Protocol Details:
    Message Format: [type: 1B][length: 4B BE][payload: N bytes]
    
    Registration Flow:
    1. Entity connects to port 8001 (OBU) or 8002 (RSU)
    2. Sends REGISTER_REQUEST with 32-byte entity ID
    3. Desktop generates EC P-256 keys and derivatives
    4. Distributes: RID, AID, DAID, SK, PK_self, PK_peer
    5. Sends REGISTER_COMPLETE and closes connection

License:
    Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
    Proprietary - See LICENSE file for terms and conditions.
"""

import socket
import struct
import threading
import time
from datetime import datetime, timezone

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config
from registration.key_generator import KeyGenerator
from database.db import Database


class RegistrationServer:
    """TCP server for entity registration and key provisioning."""

    def __init__(self, db, key_gen=None):
        self.db = db
        self.key_gen = key_gen or KeyGenerator()
        self.running = False

        # Store generated public keys for cross-distribution
        # key: entity_id (str), value: pk (bytes)
        self.public_keys = {}

        # Registered entity types
        self.registered_entities = {}

    # =========================================================================
    # WIRE PROTOCOL
    # =========================================================================

    @staticmethod
    def _pack_message(msg_type, payload=b""):
        """Pack a registration protocol message: [type][length][payload]"""
        header = struct.pack("!BI", msg_type, len(payload))
        return header + payload

    @staticmethod
    def _unpack_header(data):
        """Unpack message header. Returns (msg_type, payload_length)."""
        if len(data) < 5:
            return None, None
        msg_type, length = struct.unpack("!BI", data[:5])
        return msg_type, length

    def _recv_exact(self, sock, n):
        """Receive exactly n bytes from socket."""
        data = b""
        while len(data) < n:
            chunk = sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("Connection closed during receive")
            data += chunk
        return data

    def _recv_message(self, sock):
        """Receive one complete message. Returns (msg_type, payload)."""
        header = self._recv_exact(sock, 5)
        msg_type, length = self._unpack_header(header)
        payload = self._recv_exact(sock, length) if length > 0 else b""
        return msg_type, payload

    def _send_message(self, sock, msg_type, payload=b""):
        """Send one complete message."""
        data = self._pack_message(msg_type, payload)
        sock.sendall(data)

    # =========================================================================
    # REGISTRATION HANDLER
    # =========================================================================

    def _handle_client(self, client_sock, client_addr, entity_type, port):
        """Handle a single registration request."""
        entity_id_str = None
        try:
            print(f"[REG] Connection from {client_addr} on port {port}")

            # Step 1: Receive registration request
            msg_type, payload = self._recv_message(client_sock)

            if msg_type != config.MSG_REGISTER_REQUEST:
                print(f"[REG] ERROR: Expected REGISTER_REQUEST (0x00), got 0x{msg_type:02X}")
                self._send_message(client_sock, config.MSG_ERROR,
                                   b"Expected REGISTER_REQUEST")
                return

            if len(payload) < 1:
                print(f"[REG] ERROR: Empty registration payload")
                self._send_message(client_sock, config.MSG_ERROR,
                                   b"Empty entity ID")
                return

            # Entity ID is the payload (up to 32 bytes, may be shorter with text IDs)
            entity_id_bytes = payload.ljust(32, b"\x00")  # Pad to 32 if shorter
            entity_id_str = payload.rstrip(b"\x00").decode("utf-8", errors="replace")

            print(f"[REG] Registration request from: {entity_id_str} ({entity_type})")

            # Step 2: Generate all keys
            keys = self.key_gen.generate_all_keys(entity_id_bytes)

            # Store public key for cross-distribution
            self.public_keys[entity_id_str] = keys["pk"]
            self.registered_entities[entity_id_str] = entity_type

            print(f"[REG] Keys generated for {entity_id_str}:")
            print(f"  RID:  {len(keys['rid'])} bytes")
            print(f"  AID:  {len(keys['aid'])} bytes")
            print(f"  DAID: {len(keys['daid'])} bytes")
            print(f"  SK:   {len(keys['sk'])} bytes")
            print(f"  PK:   {len(keys['pk'])} bytes")

            # Step 3: Send keys one by one
            self._send_message(client_sock, config.MSG_RID, keys["rid"])
            print(f"  → Sent RID")

            self._send_message(client_sock, config.MSG_AID, keys["aid"])
            print(f"  → Sent AID")

            self._send_message(client_sock, config.MSG_DAID, keys["daid"])
            print(f"  → Sent DAID")

            self._send_message(client_sock, config.MSG_PRIVATE_KEY, keys["sk"])
            print(f"  → Sent SK")

            self._send_message(client_sock, config.MSG_PUBLIC_KEY_SELF, keys["pk"])
            print(f"  → Sent PK_self")

            # Step 4: Send peer public keys
            peer_pks = self._get_peer_public_keys(entity_id_str, entity_type)
            # Pack all peer PKs into one payload: [count: 1B] [pk1] [pk2] ...
            peer_payload = struct.pack("!B", len(peer_pks))
            for peer_id, peer_pk in peer_pks:
                # Each peer: [id_len: 1B] [id_bytes] [pk_bytes]
                id_bytes = peer_id.encode("utf-8")
                peer_payload += struct.pack("!B", len(id_bytes))
                peer_payload += id_bytes
                peer_payload += peer_pk
            self._send_message(client_sock, config.MSG_PUBLIC_KEY_PEER, peer_payload)
            print(f"  → Sent {len(peer_pks)} peer PK(s)")

            # Step 5: Send completion
            self._send_message(client_sock, config.MSG_REGISTER_COMPLETE)
            print(f"[REG] ✓ Registration complete for {entity_id_str}")

            # Step 6: Record in database
            ip_str = client_addr[0]
            is_emergency = (entity_id_str == "OBU2")  # OBU2 is the ambulance
            self.db.register_entity(
                entity_id=entity_id_str,
                ip_address=ip_str,
                entity_type=entity_type,
                is_emergency=is_emergency,
                public_key_hex=keys["pk"].hex()
            )

        except ConnectionError as e:
            print(f"[REG] Connection error with {client_addr}: {e}")
        except Exception as e:
            print(f"[REG] ERROR handling {client_addr}: {e}")
            import traceback
            traceback.print_exc()
            try:
                self._send_message(client_sock, config.MSG_ERROR,
                                   str(e).encode("utf-8"))
            except Exception:
                pass
        finally:
            client_sock.close()
            if entity_id_str:
                print(f"[REG] Connection closed: {entity_id_str}")

    def _get_peer_public_keys(self, entity_id, entity_type):
        """
        Get peer public keys for cross-distribution.
        OBU gets RSU's PK. RSU gets all OBU PKs.
        """
        peers = []
        for eid, etype in self.registered_entities.items():
            if eid == entity_id:
                continue  # Skip self
            if entity_type == "OBU" and etype == "RSU":
                peers.append((eid, self.public_keys[eid]))
            elif entity_type == "RSU" and etype == "OBU":
                peers.append((eid, self.public_keys[eid]))
        return peers

    # =========================================================================
    # SERVER LOOP
    # =========================================================================

    def _listen_loop(self, port, entity_type):
        """Listen for registration connections on a specific port."""
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.settimeout(1.0)  # Allow clean shutdown
        server.bind((config.DESKTOP_IP, port))
        server.listen(5)
        print(f"[REG] Listening for {entity_type} registration on port {port}")

        while self.running:
            try:
                client_sock, client_addr = server.accept()
                # Handle each client in a thread
                t = threading.Thread(
                    target=self._handle_client,
                    args=(client_sock, client_addr, entity_type, port),
                    daemon=True
                )
                t.start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"[REG] Accept error on port {port}: {e}")

        server.close()
        print(f"[REG] Stopped listening on port {port}")

    def start(self):
        """Start registration servers for OBU and RSU."""
        self.running = True

        self.obu_thread = threading.Thread(
            target=self._listen_loop,
            args=(config.REG_PORT_OBU, "OBU"),
            daemon=True
        )
        self.rsu_thread = threading.Thread(
            target=self._listen_loop,
            args=(config.REG_PORT_RSU, "RSU"),
            daemon=True
        )

        self.obu_thread.start()
        self.rsu_thread.start()
        print("[REG] Registration servers started")

    def stop(self):
        """Stop registration servers."""
        self.running = False
        print("[REG] Registration servers stopping...")


# =============================================================================
# STANDALONE TEST
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("V2X Registration Server — Standalone Mode")
    print("=" * 60)

    db = Database(config.DB_PATH)
    server = RegistrationServer(db)
    server.start()

    print()
    print(f"  OBU registration: localhost:{config.REG_PORT_OBU}")
    print(f"  RSU registration: localhost:{config.REG_PORT_RSU}")
    print()
    print("Waiting for connections... (Ctrl+C to stop)")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.stop()

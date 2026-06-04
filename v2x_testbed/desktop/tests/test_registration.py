#!/usr/bin/env python3
"""
V2X Testbed — Registration Test Client
Simulates an OBU or RSU connecting to the Desktop for registration.

Usage:
  python3 test_registration.py              # Test OBU1 registration
  python3 test_registration.py OBU2 8001    # Test OBU2
  python3 test_registration.py RSU 8002     # Test RSU
"""

import socket
import struct
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config


MSG_NAMES = {
    0x00: "REGISTER_REQUEST",
    0x01: "RID",
    0x02: "AID",
    0x03: "DAID",
    0x04: "PRIVATE_KEY",
    0x05: "PUBLIC_KEY_SELF",
    0x06: "PUBLIC_KEY_PEER",
    0x07: "REGISTER_COMPLETE",
    0xFF: "ERROR",
}


def recv_exact(sock, n):
    data = b""
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            raise ConnectionError("Connection closed")
        data += chunk
    return data


def send_message(sock, msg_type, payload=b""):
    header = struct.pack("!BI", msg_type, len(payload))
    sock.sendall(header + payload)


def recv_message(sock):
    header = recv_exact(sock, 5)
    msg_type, length = struct.unpack("!BI", header[:5])
    payload = recv_exact(sock, length) if length > 0 else b""
    return msg_type, payload


def test_registration(entity_id="OBU1", port=None):
    """Run a complete registration test."""
    if port is None:
        port = config.REG_PORT_RSU if entity_id.startswith("RSU") else config.REG_PORT_OBU

    print(f"Testing registration for {entity_id} on localhost:{port}")
    print("-" * 50)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)

    try:
        sock.connect(("127.0.0.1", port))
        print(f"✓ Connected to localhost:{port}")

        # Send registration request
        entity_bytes = entity_id.encode("utf-8")
        send_message(sock, config.MSG_REGISTER_REQUEST, entity_bytes)
        print(f"→ Sent REGISTER_REQUEST: {entity_id}")

        # Receive all responses
        received_keys = {}
        while True:
            msg_type, payload = recv_message(sock)
            name = MSG_NAMES.get(msg_type, f"UNKNOWN(0x{msg_type:02X})")

            if msg_type == config.MSG_REGISTER_COMPLETE:
                print(f"← {name}")
                print()
                print("✓ Registration complete!")
                break
            elif msg_type == config.MSG_ERROR:
                print(f"← ERROR: {payload.decode('utf-8', errors='replace')}")
                break
            elif msg_type == config.MSG_PUBLIC_KEY_PEER:
                # Parse peer keys
                if len(payload) >= 1:
                    count = payload[0]
                    print(f"← {name}: {count} peer(s), {len(payload)} bytes total")
                    offset = 1
                    for i in range(count):
                        if offset >= len(payload):
                            break
                        id_len = payload[offset]
                        offset += 1
                        peer_id = payload[offset:offset+id_len].decode("utf-8")
                        offset += id_len
                        pk_size = config.get_key_sizes()["pk"]
                        peer_pk = payload[offset:offset+pk_size]
                        offset += pk_size
                        print(f"   Peer {i+1}: {peer_id} (PK: {len(peer_pk)} bytes)")
                else:
                    print(f"← {name}: empty")
            else:
                received_keys[name] = payload
                print(f"← {name}: {len(payload)} bytes")

        print()
        print("Keys received:")
        for key_name, key_data in received_keys.items():
            print(f"  {key_name:20s}: {len(key_data):5d} bytes | {key_data[:16].hex()}...")

    except ConnectionRefusedError:
        print(f"✗ Connection refused. Is the server running?")
        print(f"  Start it with: cd desktop && python3 server.py")
    except socket.timeout:
        print(f"✗ Connection timed out")
    except Exception as e:
        print(f"✗ Error: {e}")
    finally:
        sock.close()


def test_log_sender():
    """Send a test log event to the log receiver."""
    import json
    from datetime import datetime, timezone

    print(f"\nSending test log event to localhost:{config.LOG_RECEIVER_PORT}")
    print("-" * 50)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)

    try:
        sock.connect(("127.0.0.1", config.LOG_RECEIVER_PORT))
        print(f"✓ Connected to log receiver")

        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": "AUTH_REQUEST_RECEIVED",
            "source": "OBU1",
            "target": "RSU",
            "details": {
                "pid_obu": "a1b2c3d4" * 4,
                "timestamp_diff_us": 80,
                "signature_valid": True,
            },
            "crypto_timing": {
                "signature_verify_ms": 12.5,
                "decapsulate_ms": 8.3,
            },
            "crypto_provider": "placeholder",
        }

        json_bytes = json.dumps(event).encode("utf-8")
        length_prefix = struct.pack("!I", len(json_bytes))
        sock.sendall(length_prefix + json_bytes)

        print(f"→ Sent {event['event_type']} event ({len(json_bytes)} bytes)")
        print(f"✓ Event sent successfully")

    except ConnectionRefusedError:
        print(f"✗ Connection refused. Is the server running?")
    except Exception as e:
        print(f"✗ Error: {e}")
    finally:
        sock.close()


if __name__ == "__main__":
    # Parse arguments
    entity_id = sys.argv[1] if len(sys.argv) > 1 else "OBU1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else None

    # Run registration test
    test_registration(entity_id, port)

    # Also test log sender
    test_log_sender()

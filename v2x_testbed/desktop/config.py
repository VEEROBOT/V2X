"""
V2X Authentication Testbed — Desktop Configuration
All IP addresses, ports, thresholds, and system-wide settings.
"""

import os

# =============================================================================
# NETWORK CONFIGURATION
# =============================================================================

DESKTOP_IP = "0.0.0.0"  # Listen on all interfaces

RSU_IP = "192.168.1.10"
OBU1_IP = "192.168.1.21"
OBU2_IP = "192.168.1.22"

# =============================================================================
# SERVICE PORTS
# =============================================================================

# Registration servers (Desktop listens)
REG_PORT_OBU = 8001        # OBU registration
REG_PORT_RSU = 8002        # RSU registration

# Log receiver (Desktop listens)
LOG_RECEIVER_PORT = 9000

# Dashboard (Desktop serves)
DASHBOARD_PORT = 5000

# =============================================================================
# REGISTRATION PROTOCOL MESSAGE TYPES
# =============================================================================

MSG_REGISTER_REQUEST   = 0x00
MSG_RID                = 0x01
MSG_AID                = 0x02
MSG_DAID               = 0x03
MSG_PRIVATE_KEY        = 0x04
MSG_PUBLIC_KEY_SELF    = 0x05
MSG_PUBLIC_KEY_PEER    = 0x06
MSG_REGISTER_COMPLETE  = 0x07
MSG_ERROR              = 0xFF

# =============================================================================
# CRYPTO KEY SIZES (bytes) — Lattice-based (customer's algorithm)
# Placeholder provider will use smaller sizes but the protocol handles both.
# =============================================================================

KEY_SIZE_RID    = 32
KEY_SIZE_AID    = 32
KEY_SIZE_DAID   = 736       # Partial private key
KEY_SIZE_SK     = 2528      # Full private key
KEY_SIZE_PK     = 1312      # Public key
KEY_SIZE_SIG    = 2420      # Signature
KEY_SIZE_CT     = 1088      # KEM ciphertext (capsule)

# Placeholder sizes (ECDSA/ECDH — for development)
PLACEHOLDER_KEY_SIZE_SK  = 32
PLACEHOLDER_KEY_SIZE_PK  = 65
PLACEHOLDER_KEY_SIZE_SIG = 72
PLACEHOLDER_KEY_SIZE_CT  = 65

# =============================================================================
# CRYPTO PROVIDER SELECTION
# =============================================================================

# "placeholder" uses random bytes of correct sizes for development
# "lattice" will use customer's NTL-based implementation
CRYPTO_PROVIDER = os.environ.get("V2X_CRYPTO_PROVIDER", "placeholder")

# When using placeholder, use smaller key sizes for faster development
USE_PLACEHOLDER_SIZES = (CRYPTO_PROVIDER == "placeholder")

def get_key_sizes():
    """Return key sizes based on selected crypto provider."""
    if USE_PLACEHOLDER_SIZES:
        return {
            "rid": KEY_SIZE_RID,          # Always 32
            "aid": KEY_SIZE_AID,          # Always 32
            "daid": PLACEHOLDER_KEY_SIZE_SK,  # Simplified for placeholder
            "sk": PLACEHOLDER_KEY_SIZE_SK,
            "pk": PLACEHOLDER_KEY_SIZE_PK,
            "sig": PLACEHOLDER_KEY_SIZE_SIG,
            "ct": PLACEHOLDER_KEY_SIZE_CT,
        }
    else:
        return {
            "rid": KEY_SIZE_RID,
            "aid": KEY_SIZE_AID,
            "daid": KEY_SIZE_DAID,
            "sk": KEY_SIZE_SK,
            "pk": KEY_SIZE_PK,
            "sig": KEY_SIZE_SIG,
            "ct": KEY_SIZE_CT,
        }

# =============================================================================
# AUTHENTICATION PARAMETERS
# =============================================================================

DELTA_TS_MS = 20            # Timestamp verification threshold (milliseconds)
SESSION_TIMEOUT_SEC = 300   # Session expiry (seconds)
RECEIVE_BUFFER_SIZE = 50    # RSU receive buffer (packets)

# =============================================================================
# PERFORMANCE TEST PARAMETERS
# =============================================================================

THROUGHPUT_TEST_DURATION_SEC = 120  # Customer requirement

# =============================================================================
# DATABASE
# =============================================================================

DB_PATH = os.path.join(os.path.dirname(__file__), "database", "v2x_testbed.db")

# =============================================================================
# LOGGING
# =============================================================================

LOG_LEVEL = os.environ.get("V2X_LOG_LEVEL", "INFO")

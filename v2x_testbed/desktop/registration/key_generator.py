"""
File: key_generator.py
Module: V2X Authentication Testbed — Key Generator

Purpose:
    Cryptographic key generation for the V2X ecosystem. Creates initial
    keypairs, derives registration identifiers (RID, AID, DAID), and
    generates peer-specific key material.

Author(s): Praveen Kumar
Company: Siliris Technologies Pvt. Ltd
Created: 15th February 2026
Version: 1.1

Key Operations:
    - EC P-256 keypair generation
    - Registration identifier (RID) derivation
    - Authentication identifier (AID) computation
    - Device authentication identifier (DAID) generation
    - Master secret management

Currently uses placeholder (random bytes) for development.
When customer provides lattice crypto C++ binary, this module
calls it via subprocess instead.

License:
    Copyright (c) 2026 Siliris Technologies Pvt. Ltd.
    Proprietary - See LICENSE file for terms and conditions.
"""

import os
import hashlib
import secrets

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config


class KeyGenerator:
    """Generates all keys needed for entity registration."""

    def __init__(self, master_secret=None):
        # Master secret for the testbed (in production, securely managed)
        if master_secret:
            self.master_secret = master_secret
        else:
            # Generate or load master secret
            secret_path = os.path.join(
                os.path.dirname(__file__), "..", "database", "master_secret.bin"
            )
            if os.path.exists(secret_path):
                with open(secret_path, "rb") as f:
                    self.master_secret = f.read()
                print("[KeyGen] Loaded existing master secret")
            else:
                self.master_secret = secrets.token_bytes(32)
                os.makedirs(os.path.dirname(secret_path), exist_ok=True)
                with open(secret_path, "wb") as f:
                    f.write(self.master_secret)
                print("[KeyGen] Generated new master secret")

        self.sizes = config.get_key_sizes()

    def generate_rid(self, entity_id_bytes):
        """RID = Hash(entity_id || master_secret)"""
        h = hashlib.sha256()
        h.update(entity_id_bytes)
        h.update(self.master_secret)
        return h.digest()  # 32 bytes

    def generate_aid(self, rid):
        """AID = Hash(RID || master_secret)"""
        h = hashlib.sha256()
        h.update(rid)
        h.update(self.master_secret)
        return h.digest()  # 32 bytes

    def generate_daid(self, aid):
        """
        DAID = Partial private key derived from AID.
        Placeholder: deterministic random bytes seeded from AID.
        Real: Customer's lattice-based partial key generation.
        """
        size = self.sizes["daid"]
        # Deterministic: same AID always produces same DAID
        seed = hashlib.sha256(aid + self.master_secret + b"DAID").digest()
        # Expand seed to required size using HKDF-like expansion
        return self._expand_key(seed, size)

    def generate_keypair(self, aid):
        """
        Generate (SK, PK) keypair for an entity.
        Placeholder: Real ECDSA P-256 keypair via OpenSSL.
        Real: Customer's lattice-based key generation.
        """
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.serialization import (
            Encoding, PublicFormat, NoEncryption
        )

        # Generate a real EC P-256 keypair
        private_key = ec.generate_private_key(ec.SECP256R1())

        # Extract raw private key bytes (32 bytes - the scalar)
        private_numbers = private_key.private_numbers()
        sk = private_numbers.private_value.to_bytes(32, byteorder='big')

        # Extract raw public key bytes (65 bytes - uncompressed point)
        pk = private_key.public_key().public_bytes(
            Encoding.X962,
            PublicFormat.UncompressedPoint
        )

        return sk, pk

    def generate_all_keys(self, entity_id_bytes):
        """
        Complete key generation for one entity.
        Returns dict with all key material.
        """
        rid = self.generate_rid(entity_id_bytes)
        aid = self.generate_aid(rid)
        daid = self.generate_daid(aid)
        sk, pk = self.generate_keypair(aid)

        return {
            "rid": rid,
            "aid": aid,
            "daid": daid,
            "sk": sk,
            "pk": pk,
        }

    def _expand_key(self, seed, length):
        """Expand a 32-byte seed to arbitrary length using SHA-256 chaining."""
        result = b""
        counter = 0
        while len(result) < length:
            h = hashlib.sha256()
            h.update(seed)
            h.update(counter.to_bytes(4, "big"))
            result += h.digest()
            counter += 1
        return result[:length]


# =============================================================================
# SELF-TEST
# =============================================================================

if __name__ == "__main__":
    kg = KeyGenerator(master_secret=b"test_secret_32bytes_placeholder!")
    sizes = config.get_key_sizes()

    entity_id = b"OBU1" + b"\x00" * 28  # Pad to 32 bytes

    keys = kg.generate_all_keys(entity_id)

    print(f"Provider: {config.CRYPTO_PROVIDER}")
    print(f"RID:  {len(keys['rid']):5d} bytes  (expected {sizes['rid']})")
    print(f"AID:  {len(keys['aid']):5d} bytes  (expected {sizes['aid']})")
    print(f"DAID: {len(keys['daid']):5d} bytes  (expected {sizes['daid']})")
    print(f"SK:   {len(keys['sk']):5d} bytes  (expected {sizes['sk']})")
    print(f"PK:   {len(keys['pk']):5d} bytes  (expected {sizes['pk']})")
    print()
    print(f"RID hex: {keys['rid'].hex()[:64]}...")
    print(f"PK hex:  {keys['pk'].hex()[:64]}...")

    # Verify determinism
    keys2 = kg.generate_all_keys(entity_id)
    assert keys["rid"] == keys2["rid"], "RID not deterministic!"
    assert keys["pk"] == keys2["pk"], "PK not deterministic!"
    print("\n✓ Keys are deterministic (same input → same output)")

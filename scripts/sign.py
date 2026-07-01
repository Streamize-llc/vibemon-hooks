#!/usr/bin/env python3
"""
sign.py — sign the built dist artifacts (run by CI at release time).

Reads the secret seed from env `VIBEMON_SIGNING_SEED` (hex, 64 chars), signs
each artifact's raw bytes with Ed25519, and writes `<artifact>.sig` containing
the base64 of the 64-byte signature. Also self-checks that the signature
verifies against the committed public key in src/release_pubkey.py, so a
key/secret mismatch fails the release instead of shipping a bad signature.

    VIBEMON_SIGNING_SEED=<hex> python3 scripts/sign.py

Signs: dist/install.sh, dist/install.ps1 (extend ARTIFACTS as needed).
"""

import base64
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
import ed25519  # noqa: E402
from release_pubkey import RELEASE_PUBKEY_HEX  # noqa: E402

ARTIFACTS = ["dist/install.sh", "dist/install.ps1"]


def main():
    seed_hex = os.environ.get("VIBEMON_SIGNING_SEED", "").strip()
    try:
        seed = bytes.fromhex(seed_hex)
    except ValueError:
        seed = b""
    if len(seed) != 32:
        print("ERROR: VIBEMON_SIGNING_SEED must be 64 hex chars (32 bytes)", file=sys.stderr)
        return 1

    pub = ed25519.publickey(seed)
    committed = bytes.fromhex(RELEASE_PUBKEY_HEX.strip())
    if pub != committed:
        print("ERROR: secret seed does not match committed src/release_pubkey.py.\n"
              "       Run scripts/keygen.py and update the secret + pubkey together.",
              file=sys.stderr)
        return 1

    for rel in ARTIFACTS:
        path = os.path.join(ROOT, rel)
        with open(path, "rb") as f:
            data = f.read()
        sig = ed25519.signature(data, seed, pub)
        # Self-check: the signature we just produced MUST verify. Fail-closed.
        ed25519.checkvalid(sig, data, pub)
        sig_path = path + ".sig"
        with open(sig_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(base64.b64encode(sig).decode("ascii") + "\n")
        print(f"signed {rel} -> {rel}.sig")
    return 0


if __name__ == "__main__":
    sys.exit(main())

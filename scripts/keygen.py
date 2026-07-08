#!/usr/bin/env python3
"""
keygen.py — generate (or rotate) the VibeMon release-signing keypair.

Run this ONCE to activate signed auto-updates:

    python3 scripts/keygen.py

It:
  1. generates a fresh 32-byte Ed25519 secret seed (os.urandom),
  2. writes the PUBLIC key into src/release_pubkey.py (commit this change),
  3. prints the SECRET seed (hex) exactly once.

Store the printed secret as the GitHub Actions repository secret named
`VIBEMON_SIGNING_SEED` (Settings -> Secrets and variables -> Actions).
NEVER commit it, paste it in chat, or store it anywhere else. If it leaks,
run this script again to rotate and cut a new release.

Rotating invalidates old signatures, which is fine: each new release is signed
with the current key and clients verify against the current committed pubkey.
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
import ed25519  # noqa: E402

PUBKEY_FILE = os.path.join(ROOT, "src", "release_pubkey.py")


def main():
    seed = os.urandom(32)
    pub = ed25519.publickey(seed)

    with open(PUBKEY_FILE, encoding="utf-8") as f:
        content = f.read()
    new = re.sub(
        r'RELEASE_PUBKEY_HEX = "[0-9a-fA-F]*"',
        f'RELEASE_PUBKEY_HEX = "{pub.hex()}"',
        content,
    )
    if new == content:
        print("ERROR: could not find RELEASE_PUBKEY_HEX assignment to update", file=sys.stderr)
        return 1
    with open(PUBKEY_FILE, "w", encoding="utf-8", newline="\n") as f:
        f.write(new)

    print("=" * 70)
    print("VibeMon release key generated.")
    print("=" * 70)
    print(f"\nPUBLIC key written to src/release_pubkey.py (COMMIT this):\n  {pub.hex()}")
    print("\nSECRET seed — store as GitHub Actions secret VIBEMON_SIGNING_SEED,")
    print("then clear your terminal. Shown ONCE, never recoverable:\n")
    print(f"  {seed.hex()}\n")
    print("Next: rebuild (python3 scripts/build.py), commit release_pubkey.py")
    print("+ dist/, then tag a release so CI signs it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

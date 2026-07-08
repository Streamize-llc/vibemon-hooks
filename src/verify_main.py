"""
verify_main.py — client-side installer verifier (used by notify.sh's auto-update).

Invoked as `python3 - <installer_path> <sig_path>` with ed25519.py + release_pubkey.py
concatenated ABOVE it (see scripts/build.py's notify.sh embed). Exit codes:
    0  signature valid  -> caller may execute the installer
    1  signature INVALID -> caller MUST NOT execute (tampered / wrong key)
    2  usage/IO error    -> caller MUST NOT execute
    3  no release key configured (placeholder) -> caller MUST NOT execute
Anything non-zero => do not run. Fail-closed by construction.

Also importable/standalone for tests: falls back to real imports when the
symbols aren't already in scope from the embed.
"""

import base64
import sys

try:
    checkvalid  # provided by the embedded ed25519.py
except NameError:  # standalone / test import
    from ed25519 import checkvalid

try:
    RELEASE_PUBKEY_HEX  # provided by the embedded release_pubkey.py
except NameError:
    from release_pubkey import RELEASE_PUBKEY_HEX


def verify_file(installer_path, sig_path, pubkey_hex):
    pubkey_hex = (pubkey_hex or "").strip()
    try:
        pk = bytes.fromhex(pubkey_hex)
    except ValueError:
        return 3
    # Placeholder / unconfigured key (all-zero or wrong length) => fail-closed.
    if len(pk) != 32 or pk == b"\x00" * 32:
        return 3
    try:
        with open(installer_path, "rb") as f:
            data = f.read()
        with open(sig_path, "rb") as f:
            sig = base64.b64decode(f.read().strip())
    except (OSError, ValueError):
        return 2
    try:
        checkvalid(sig, data, pk)
    except Exception:  # noqa: BLE001 — ANY failure means reject
        return 1
    return 0


def main(argv):
    if len(argv) != 3:
        return 2
    return verify_file(argv[1], argv[2], RELEASE_PUBKEY_HEX)


if __name__ == "__main__":
    sys.exit(main(sys.argv))

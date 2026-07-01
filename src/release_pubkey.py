"""
release_pubkey.py — the ONE source of truth for VibeMon's release-signing
public key. The matching SECRET seed lives ONLY in the GitHub Actions secret
`VIBEMON_SIGNING_SEED` and is NEVER committed here.

The auto-updater (notify.sh / notify.py) verifies every downloaded installer
against this key before executing it. Rotate with `python3 scripts/keygen.py`,
which overwrites the value below and prints a new secret seed to store in the
GitHub secret.

FAIL-CLOSED: while this is the 64-hex-char placeholder of all zeros (i.e. no
real key has been generated yet), signature verification cannot succeed, so the
auto-updater refuses to run ANY downloaded installer. That is the safe default:
no signed key => no auto-update, never an unsigned exec. Run keygen to activate.
"""

RELEASE_PUBKEY_HEX = "0000000000000000000000000000000000000000000000000000000000000000"

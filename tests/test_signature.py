"""
test_signature.py — proves the signed-auto-update chain is correct AND
fail-closed. This is the security-critical test: a bug that makes verification
wrongly PASS would silently reopen the RCE channel, so we assert both that valid
signatures are accepted and that every tampering is rejected.

Covers:
  1. RFC 8032 known-answer vector (our Ed25519 math matches the standard).
  2. Round-trip: keygen -> sign -> verify passes.
  3. Fail-closed: tampered file / wrong key / flipped-bit sig / truncated sig /
     placeholder (unconfigured) key all make verify_main.verify_file return
     non-zero (i.e. "do not execute").
  4. Cross-check against PyNaCl when it is importable (CI installs it).
"""

import base64
import binascii
import os

import ed25519
import verify_main


def _sig_file(tmp_path, sig_bytes):
    p = tmp_path / "install.sh.sig"
    p.write_text(base64.b64encode(sig_bytes).decode("ascii") + "\n")
    return str(p)


def test_rfc8032_known_answer():
    # RFC 8032 Section 7.1, TEST 2.
    seed = binascii.unhexlify(
        "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb")
    msg = binascii.unhexlify("72")
    assert ed25519.publickey(seed).hex() == (
        "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c")
    sig = ed25519.signature(msg, seed, ed25519.publickey(seed))
    assert sig.hex() == (
        "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
        "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00")
    assert ed25519.checkvalid(sig, msg, ed25519.publickey(seed)) is True


def test_roundtrip_and_verify_file(tmp_path):
    seed = os.urandom(32)
    pk = ed25519.publickey(seed)
    installer = tmp_path / "install.sh"
    installer.write_bytes(b"#!/bin/sh\necho hello\n")
    data = installer.read_bytes()
    sig = ed25519.signature(data, seed, pk)
    sig_path = _sig_file(tmp_path, sig)
    assert verify_main.verify_file(str(installer), sig_path, pk.hex()) == 0


def test_fail_closed_tampered_file(tmp_path):
    seed = os.urandom(32)
    pk = ed25519.publickey(seed)
    installer = tmp_path / "install.sh"
    installer.write_bytes(b"#!/bin/sh\necho hello\n")
    sig = ed25519.signature(installer.read_bytes(), seed, pk)
    sig_path = _sig_file(tmp_path, sig)
    installer.write_bytes(b"#!/bin/sh\nrm -rf ~\n")  # attacker swaps the bytes
    assert verify_main.verify_file(str(installer), sig_path, pk.hex()) == 1


def test_fail_closed_wrong_key(tmp_path):
    seed = os.urandom(32)
    pk = ed25519.publickey(seed)
    installer = tmp_path / "install.sh"
    installer.write_bytes(b"payload")
    sig_path = _sig_file(tmp_path, ed25519.signature(installer.read_bytes(), seed, pk))
    attacker_pk = ed25519.publickey(os.urandom(32))
    assert verify_main.verify_file(str(installer), sig_path, attacker_pk.hex()) == 1


def test_fail_closed_flipped_sig_bit(tmp_path):
    seed = os.urandom(32)
    pk = ed25519.publickey(seed)
    installer = tmp_path / "install.sh"
    installer.write_bytes(b"payload")
    sig = bytearray(ed25519.signature(installer.read_bytes(), seed, pk))
    sig[0] ^= 0x01
    sig_path = _sig_file(tmp_path, bytes(sig))
    assert verify_main.verify_file(str(installer), sig_path, pk.hex()) == 1


def test_fail_closed_truncated_sig(tmp_path):
    seed = os.urandom(32)
    pk = ed25519.publickey(seed)
    installer = tmp_path / "install.sh"
    installer.write_bytes(b"payload")
    sig = ed25519.signature(installer.read_bytes(), seed, pk)[:-1]
    sig_path = _sig_file(tmp_path, sig)
    assert verify_main.verify_file(str(installer), sig_path, pk.hex()) == 1


def test_fail_closed_placeholder_key(tmp_path):
    # The shipped default (all-zero placeholder) must never verify anything.
    seed = os.urandom(32)
    pk = ed25519.publickey(seed)
    installer = tmp_path / "install.sh"
    installer.write_bytes(b"payload")
    sig_path = _sig_file(tmp_path, ed25519.signature(installer.read_bytes(), seed, pk))
    placeholder = "0" * 64
    assert verify_main.verify_file(str(installer), sig_path, placeholder) == 3
    assert verify_main.verify_file(str(installer), sig_path, "") == 3
    assert verify_main.verify_file(str(installer), sig_path, "not-hex") == 3


def test_committed_pubkey_is_valid_or_placeholder():
    # Guard: release_pubkey.py must be exactly 64 hex chars (a real key) or the
    # all-zero placeholder — never malformed (which would silently disable updates
    # in a confusing way vs. the documented fail-closed placeholder).
    from release_pubkey import RELEASE_PUBKEY_HEX
    v = RELEASE_PUBKEY_HEX.strip()
    assert len(v) == 64
    int(v, 16)  # raises if not hex


def test_cross_check_pynacl(tmp_path):
    try:
        from nacl.signing import SigningKey, VerifyKey
    except ImportError:
        import pytest
        pytest.skip("pynacl not installed")
    seed = os.urandom(32)
    pk = ed25519.publickey(seed)
    msg = os.urandom(200)
    # our signature verifies under pynacl
    VerifyKey(pk).verify(msg, ed25519.signature(msg, seed, pk))
    # pynacl's signature verifies under ours
    sk = SigningKey(seed)
    assert bytes(sk.verify_key) == pk
    assert ed25519.checkvalid(sk.sign(msg).signature, msg, pk) is True

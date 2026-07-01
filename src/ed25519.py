"""
ed25519.py — self-contained, stdlib-only Ed25519 (RFC 8032).

Why this exists: the auto-updater must verify a signature over the installer
BEFORE executing it, and the client environment is guaranteed to have `python3`
(install.sh checks for it; notify.py *is* python3) but NOTHING else — no pip
packages, no `minisign`/`openssl` binary, cross-platform (macOS/Linux/Windows).
So verification is done here in pure Python on stdlib `hashlib.sha512` only.

This is the well-known public-domain reference implementation from the Ed25519
authors (D. J. Bernstein et al.) / RFC 8032 Appendix A, unmodified in its math.
It is deliberately the simple (slow) reference, not an optimized one: the client
verifies a single signature at most once per day, so clarity/auditability beats
speed, and matching the reference exactly is what lets the CI test check it
against RFC 8032 test vectors + an independent library (PyNaCl).

Used by:
  - src/verify.py  — the client-side verifier CLI (embedded into notify.sh /
    shipped in the Windows bundle).
  - scripts/sign.py / scripts/keygen.py — release-time signing (CI) + one-time
    key generation. Signing uses the SAME code path so the CI round-trip test
    (`sign` here → `verify` here → PyNaCl) proves the whole chain.

SECURITY: `checkvalid()` RAISES on any failure (bad signature, wrong length,
off-curve point). Callers MUST treat any exception as "reject" (fail-closed).
"""

import hashlib

b = 256
q = 2 ** 255 - 19
L = 2 ** 252 + 27742317777372353535851937790883648493


def _H(m):
    return hashlib.sha512(m).digest()


def _expmod(base, e, m):
    if e == 0:
        return 1
    t = _expmod(base, e // 2, m) ** 2 % m
    if e & 1:
        t = (t * base) % m
    return t


def _inv(x):
    return _expmod(x, q - 2, q)


d = -121665 * _inv(121666) % q
_I = _expmod(2, (q - 1) // 4, q)


def _xrecover(y):
    xx = (y * y - 1) * _inv(d * y * y + 1)
    x = _expmod(xx, (q + 3) // 8, q)
    if (x * x - xx) % q != 0:
        x = (x * _I) % q
    if x % 2 != 0:
        x = q - x
    return x


_By = 4 * _inv(5) % q
_Bx = _xrecover(_By)
B = [_Bx % q, _By % q]


def _edwards(P, Q):
    x1, y1 = P
    x2, y2 = Q
    x3 = (x1 * y2 + x2 * y1) * _inv(1 + d * x1 * x2 * y1 * y2)
    y3 = (y1 * y2 + x1 * x2) * _inv(1 - d * x1 * x2 * y1 * y2)
    return [x3 % q, y3 % q]


def _scalarmult(P, e):
    if e == 0:
        return [0, 1]
    Q = _scalarmult(P, e // 2)
    Q = _edwards(Q, Q)
    if e & 1:
        Q = _edwards(Q, P)
    return Q


def _encodeint(y):
    bits = [(y >> i) & 1 for i in range(b)]
    return bytes(sum(bits[i * 8 + j] << j for j in range(8)) for i in range(b // 8))


def _encodepoint(P):
    x, y = P
    bits = [(y >> i) & 1 for i in range(b - 1)] + [x & 1]
    return bytes(sum(bits[i * 8 + j] << j for j in range(8)) for i in range(b // 8))


def _bit(h, i):
    return (h[i // 8] >> (i % 8)) & 1


def _Hint(m):
    h = _H(m)
    return sum(2 ** i * _bit(h, i) for i in range(2 * b))


def publickey(seed):
    """32-byte secret seed -> 32-byte public key."""
    if len(seed) != 32:
        raise ValueError("seed must be 32 bytes")
    h = _H(seed)
    a = 2 ** (b - 2) + sum(2 ** i * _bit(h, i) for i in range(3, b - 2))
    A = _scalarmult(B, a)
    return _encodepoint(A)


def signature(m, seed, pk):
    """Sign message bytes `m` with 32-byte seed + its 32-byte public key -> 64-byte sig."""
    h = _H(seed)
    a = 2 ** (b - 2) + sum(2 ** i * _bit(h, i) for i in range(3, b - 2))
    r = _Hint(bytes(h[i] for i in range(b // 8, b // 4)) + m)
    R = _scalarmult(B, r)
    S = (r + _Hint(_encodepoint(R) + pk + m) * a) % L
    return _encodepoint(R) + _encodeint(S)


def _isoncurve(P):
    x, y = P
    return (-x * x + y * y - 1 - d * x * x * y * y) % q == 0


def _decodeint(s):
    return sum(2 ** i * _bit(s, i) for i in range(0, b))


def _decodepoint(s):
    y = sum(2 ** i * _bit(s, i) for i in range(0, b - 1))
    x = _xrecover(y)
    if x & 1 != _bit(s, b - 1):
        x = q - x
    P = [x, y]
    if not _isoncurve(P):
        raise ValueError("decoding point that is not on curve")
    return P


def checkvalid(sig, m, pk):
    """Verify 64-byte `sig` over message `m` under 32-byte public key `pk`.
    RAISES ValueError on ANY failure — callers MUST treat that as reject."""
    if len(sig) != b // 4:
        raise ValueError("signature length is wrong")
    if len(pk) != b // 8:
        raise ValueError("public-key length is wrong")
    R = _decodepoint(sig[0:b // 8])
    A = _decodepoint(pk)
    S = _decodeint(sig[b // 8:b // 4])
    h = _Hint(_encodepoint(R) + pk + m)
    if _scalarmult(B, S) != _edwards(R, _scalarmult(A, h)):
        raise ValueError("signature does not pass verification")
    return True

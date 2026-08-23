"""Ed25519 (RFC 8032) in pure Python, public-domain reference construction.

Vendored so this toolkit runs on a stock python3 with no pip install. It is
slow (roughly a second per signature) and that is fine: we sign twice, ever.

If `cryptography` is installed it is used instead; see keyutil.py. Both paths
are cross-checked by `python3 -m selftest`.
"""
import hashlib
import os

b = 256
q = 2 ** 255 - 19
L = 2 ** 252 + 27742317777372353535851937790883648493


def _h(m):
    return hashlib.sha512(m).digest()


def _inv(x):
    return pow(x, q - 2, q)


d = -121665 * _inv(121666) % q
I = pow(2, (q - 1) // 4, q)


def _xrecover(y):
    xx = (y * y - 1) * _inv(d * y * y + 1)
    x = pow(xx, (q + 3) // 8, q)
    if (x * x - xx) % q != 0:
        x = (x * I) % q
    if x % 2 != 0:
        x = q - x
    return x


By = 4 * _inv(5)
Bx = _xrecover(By)
B = (Bx % q, By % q)


def _edwards(P, Q):
    x1, y1 = P
    x2, y2 = Q
    x3 = (x1 * y2 + x2 * y1) * _inv(1 + d * x1 * x2 * y1 * y2)
    y3 = (y1 * y2 + x1 * x2) * _inv(1 - d * x1 * x2 * y1 * y2)
    return (x3 % q, y3 % q)


def _scalarmult(P, e):
    # Iterative double-and-add: the recursive reference blows the stack on
    # some hardened builds where the default recursion limit is lowered.
    R = (0, 1)
    Q = P
    while e > 0:
        if e & 1:
            R = _edwards(R, Q)
        Q = _edwards(Q, Q)
        e >>= 1
    return R


def _encodeint(y):
    return y.to_bytes(32, "little")


def _encodepoint(P):
    x, y = P
    n = y | ((x & 1) << 255)
    return n.to_bytes(32, "little")


def _hint(m):
    return int.from_bytes(_h(m), "little")


def publickey(sk: bytes) -> bytes:
    """32-byte seed -> 32 raw public key bytes."""
    if len(sk) != 32:
        raise ValueError("seed must be 32 bytes")
    hs = _h(sk)
    a = 2 ** (b - 2) + sum(2 ** i for i in range(3, b - 2) if (hs[i // 8] >> (i % 8)) & 1)
    return _encodepoint(_scalarmult(B, a))


def sign(message: bytes, sk: bytes, pk: bytes) -> bytes:
    """Detached 64-byte signature over `message`."""
    hs = _h(sk)
    a = 2 ** (b - 2) + sum(2 ** i for i in range(3, b - 2) if (hs[i // 8] >> (i % 8)) & 1)
    r = _hint(hs[32:64] + message)
    R = _scalarmult(B, r)
    S = (r + _hint(_encodepoint(R) + pk + message) * a) % L
    return _encodepoint(R) + _encodeint(S)


def generate_seed() -> bytes:
    return os.urandom(32)

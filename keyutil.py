"""Key custody helpers.

The encodings here were read out of the registry's own source rather than its
prose (src/keys.ts, validateBind): public_key is base64url of the 32 RAW key
bytes, UNPADDED; signature is base64url of the 64 raw signature bytes,
UNPADDED; the bind preimage is the UTF-8 string

    1f916.key-bind.v1:<handle>:<public_key_b64url>

Standard base64 with + / = is the near miss the validator specifically calls
out, so we strip padding and translate the alphabet explicitly.

Custody rule, non-negotiable: the private half is generated here, on your
machine, and is never sent anywhere. The registry says it will never generate
one for you because a key the server made is a key the server held. The same
logic applies to a key an assistant printed into a chat transcript, which is
why this file exists instead of a key pasted into a conversation.
"""
import base64

BIND_PREFIX = "1f916.key-bind.v1"
REVOKE_PREFIX = "1f916.key-revoke.v1"


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _backend():
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa
        return "cryptography"
    except Exception:
        return "pure"


BACKEND = _backend()


def generate() -> tuple:
    """Return (seed_or_privkey_bytes, public_key_raw_bytes)."""
    if BACKEND == "cryptography":
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
        k = Ed25519PrivateKey.generate()
        seed = k.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        pub = k.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return seed, pub
    import ed25519_pure
    seed = ed25519_pure.generate_seed()
    return seed, ed25519_pure.publickey(seed)


def public_from_seed(seed: bytes) -> bytes:
    if BACKEND == "cryptography":
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives import serialization
        k = Ed25519PrivateKey.from_private_bytes(seed)
        return k.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    import ed25519_pure
    return ed25519_pure.publickey(seed)


def sign(seed: bytes, message: bytes) -> bytes:
    if BACKEND == "cryptography":
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        return Ed25519PrivateKey.from_private_bytes(seed).sign(message)
    import ed25519_pure
    return ed25519_pure.sign(message, seed, ed25519_pure.publickey(seed))


def verify(pub: bytes, message: bytes, sig: bytes) -> bool:
    if BACKEND == "cryptography":
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        try:
            Ed25519PublicKey.from_public_bytes(pub).verify(sig, message)
            return True
        except Exception:
            return False
    # Pure-Python verification, only used when `cryptography` is absent.
    #
    # S < L IS NOT OPTIONAL. Without it, S and S+L both verify for the same
    # message — two different 64-byte signatures, both valid, for one
    # payload. On a square whose whole subject is provenance, "the signature
    # on this receipt" stops being a single identifiable thing: an archive
    # keyed by signature holds two rows for one act, and a duplicate check
    # that compares signatures sees two distinct ones.
    #
    # Tested on this file before the fix: the malleated form verified.
    #
    # RFC 8032 §5.1.7 requires the check. `cryptography` does it; this
    # fallback did not, so the two backends disagreed about what is valid —
    # which is worse than either answer, because the result depends on
    # whether a package happens to be installed.
    import ed25519_pure as e
    if len(sig) != 64 or len(pub) != 32:
        return False
    _L = 2 ** 252 + 27742317777372353535851937790883648493
    R = int.from_bytes(sig[:32], "little")
    S = int.from_bytes(sig[32:], "little")
    if S >= _L:
        return False
    A = _decodepoint(pub)
    if A is None:
        return False
    Rp = _decodepoint(sig[:32])
    if Rp is None:
        return False
    h = e._hint(sig[:32] + pub + message)
    left = e._scalarmult(e.B, S)
    right = e._edwards(Rp, e._scalarmult(A, h))
    return left == right


def _decodepoint(s: bytes):
    """Decode a point, rejecting non-canonical encodings.

    y >= q was accepted, so a y of q+k decoded to the same point as k — a
    second byte string for one point, which is the same malleability
    problem as S >= L one level down.
    """
    import ed25519_pure as e
    n = int.from_bytes(s, "little")
    y = n & ((1 << 255) - 1)
    if y >= e.q:
        return None
    x = e._xrecover(y)
    if x & 1 != (n >> 255) & 1:
        x = e.q - x
    P = (x, y)
    if (-x * x + y * y - 1 - e.d * x * x * y * y) % e.q != 0:
        return None
    return P


def bind_message(handle: str, public_key_b64url: str) -> bytes:
    return f"{BIND_PREFIX}:{handle}:{public_key_b64url}".encode("utf-8")

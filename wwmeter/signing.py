"""Ed25519 signatures for Waveband's releases (RFC 8032), in plain Python.

A release's ``SHA256SUMS.txt`` is signed with a private key that never leaves the builder's PC
(``tools\\release_key.py`` makes it; ``tools\\build_release.py`` signs with it) and the signature
is published beside it as ``SHA256SUMS.txt.sig``. Waveband carries the matching public key
(``RELEASE_KEY`` below) and installs an update only when the signature checks out, so whoever
might get into the GitHub account still cannot ship one: they would need that key file too.

This is the reference algorithm of RFC 8032, section 6, checked against the RFC's own test
vectors in ``tests\\test_signing.py``. It is slow next to a C library (a tenth of a second to
check a signature), which does not matter for one check per update, and needs nothing installed.
"""

from __future__ import annotations

import hashlib
import os

# The public half of the release key, as 64 hex digits. Empty until ``tools\\release_key.py`` has
# made one: then no signature is asked for, and updates are not installed at all.
RELEASE_KEY = "73221279491bd8a81b0579eae5c9da2332771d648af6915b0e72b275396ae6fc"

_P = 2 ** 255 - 19
_Q = 2 ** 252 + 27742317777372353535851937790883648493


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


_D = -121665 * _inv(121666) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def _add(a, b):
    p1 = (a[1] - a[0]) * (b[1] - b[0]) % _P
    p2 = (a[1] + a[0]) * (b[1] + b[0]) % _P
    c = 2 * a[3] * b[3] * _D % _P
    d = 2 * a[2] * b[2] % _P
    e, f, g, h = p2 - p1, d - c, d + c, p2 + p1
    return (e * f, g * h, f * g, e * h)


def _mul(s: int, point):
    result = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            result = _add(result, point)
        point = _add(point, point)
        s >>= 1
    return result


def _equal(a, b) -> bool:
    return (a[0] * b[2] - b[0] * a[2]) % _P == 0 and (a[1] * b[2] - b[1] * a[2]) % _P == 0


def _recover_x(y: int, sign: int):
    if y >= _P:
        return None
    x2 = (y * y - 1) * _inv(_D * y * y + 1)
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P != 0:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


_GY = 4 * _inv(5) % _P
_GX = _recover_x(_GY, 0)
_G = (_GX, _GY, 1, _GX * _GY % _P)


def _compress(point) -> bytes:
    zinv = _inv(point[2])
    x, y = point[0] * zinv % _P, point[1] * zinv % _P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decompress(data: bytes):
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % _P)


def _expand(secret: bytes) -> tuple[int, bytes]:
    h = hashlib.sha512(secret).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def _hash_q(data: bytes) -> int:
    return int.from_bytes(hashlib.sha512(data).digest(), "little") % _Q


def new_secret() -> bytes:
    return os.urandom(32)


def public_key(secret: bytes) -> bytes:
    return _compress(_mul(_expand(secret)[0], _G))


def sign(secret: bytes, message: bytes) -> bytes:
    a, prefix = _expand(secret)
    public = _compress(_mul(a, _G))
    r = _hash_q(prefix + message)
    big_r = _compress(_mul(r, _G))
    s = (r + _hash_q(big_r + public + message) * a) % _Q
    return big_r + int.to_bytes(s, 32, "little")


def verify(public: bytes, message: bytes, signature: bytes) -> bool:
    if len(public) != 32 or len(signature) != 64:
        return False
    a = _decompress(public)
    r = _decompress(signature[:32])
    if a is None or r is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _Q:
        return False
    h = _hash_q(signature[:32] + public + message)
    return _equal(_mul(s, _G), _add(r, _mul(h, a)))

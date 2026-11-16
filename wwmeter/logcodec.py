"""Client.log byte obfuscation.

Each plaintext byte is XORed with one of two keys chosen by the byte's parity: even bytes with
``KEY_EVEN``, odd bytes with ``KEY_ODD``. Both keys are odd, so the parity of the stored byte is the
opposite of the plaintext's, which makes the transform stateless and reversible byte by byte.
"""

from __future__ import annotations

KEY_EVEN = 0xA5
KEY_ODD = 0xEF

_BOM = b"\xef\xbb\xbf"


def decode_table(key_even: int = KEY_EVEN, key_odd: int = KEY_ODD) -> bytes:
    if not (key_even & 1 and key_odd & 1):
        raise ValueError("both keys must be odd for the transform to be reversible")
    # stored odd  <- plaintext even ^ key_even ; stored even <- plaintext odd ^ key_odd
    return bytes((c ^ (key_even if c & 1 else key_odd)) for c in range(256))


def encode_table(key_even: int = KEY_EVEN, key_odd: int = KEY_ODD) -> bytes:
    return bytes((p ^ (key_odd if p & 1 else key_even)) for p in range(256))


PLAIN = bytes(range(256))
DECODE = decode_table()
ENCODE = encode_table()


def detect_table(head: bytes) -> bytes:
    """Pick the decode table from the first bytes of a log file.

    A log starts with an optional UTF-8 BOM followed by ``[2026...`` (the timestamp of the first
    line), which is enough known plaintext to recover both keys. The BOM itself is sometimes
    written scrambled and sometimes not, independently of the text after it, so only the text is
    trusted. Falls back to the known keys when the header is too short or unrecognisable.
    """
    # All three BOM bytes are odd, so they share one key and their XOR differences survive
    # scrambling. Only the last two are compared: the first byte has been seen to vary.
    has_bom = len(head) >= 3 and head[1] ^ head[2] == _BOM[1] ^ _BOM[2]
    start = 3 if has_bom else 0
    text = head[start : start + 5]
    if len(text) < 5:
        return DECODE
    if text[:2] == b"[2" and text[2:].isdigit():
        return PLAIN
    key_odd = text[0] ^ ord("[")
    key_even = text[1] ^ ord("2")
    if key_odd & 1 and key_even & 1:
        table = decode_table(key_even, key_odd)
        if text.translate(table)[2:].isdigit():
            return table
    return DECODE


def decode(data: bytes, table: bytes = DECODE) -> bytes:
    return data.translate(table)


def encode(data: bytes) -> bytes:
    return data.translate(ENCODE)

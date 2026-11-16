"""The key Waveband's releases are signed with.

    .venv\\Scripts\\python tools\\release_key.py new          # once: make the key, put its public half in the code
    .venv\\Scripts\\python tools\\release_key.py protect      # lock an older plain key file with a passphrase
    .venv\\Scripts\\python tools\\release_key.py passphrase   # change the passphrase
    .venv\\Scripts\\python tools\\release_key.py public       # print the public half
    .venv\\Scripts\\python tools\\release_key.py sign FILE    # write FILE.sig (build_release.py does this)
    .venv\\Scripts\\python tools\\release_key.py verify FILE  # check FILE.sig against the code's public key

The private half lives outside the project, in ``%USERPROFILE%\\.waveband\\release-signing-key.txt``
(or wherever ``WAVEBAND_RELEASE_KEY`` points), locked with a passphrase: the file holds the key
XORed with 32 bytes derived from the passphrase by scrypt (128 MB of memory, about half a second,
so guessing passphrases is slow), with a random salt. A copy of the file is no use without the
passphrase, so a backup service, a stray upload or a program reading files cannot sign an update
with it. Something that watches the keyboard while the passphrase is typed still could: the
passphrase is the last lock, so give it its own, long one, kept in a password manager.

Keep a copy of the file in the password manager too: without the file and the passphrase no
further update can be signed, and installed copies would have to be updated by hand once, to a
version with a new key. Never commit, upload or share either. The passphrase is asked for in the
terminal and never written anywhere.
"""

from __future__ import annotations

import getpass
import hashlib
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from wwmeter import signing  # noqa: E402

KEY_PATH = os.environ.get("WAVEBAND_RELEASE_KEY") or os.path.join(
    os.path.expanduser("~"), ".waveband", "release-signing-key.txt")
CODE = os.path.join(ROOT, "wwmeter", "signing.py")
_FORMAT = "waveband-release-key 2 scrypt"
_N, _R, _P = 2 ** 17, 8, 1  # scrypt's cost: 128 MB and about half a second per try
_MIN_PASSPHRASE = 12


class Locked(Exception):
    """The key could not be had: no file, a wrong passphrase, or no terminal to ask in."""


def _derive(passphrase: str, salt: bytes, n: int = _N, r: int = _R, p: int = _P) -> bytes:
    return hashlib.scrypt(passphrase.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=256 * 1024 * 1024, dklen=32)


def lock(secret: bytes, passphrase: str, n: int = _N) -> str:
    """The key file's text for ``secret`` under ``passphrase``."""
    salt = os.urandom(16)
    mask = _derive(passphrase, salt, n)
    hidden = bytes(a ^ b for a, b in zip(secret, mask))
    return (f"{_FORMAT}\nsalt {salt.hex()}\ncost {n} {_R} {_P}\nkey {hidden.hex()}\n"
            f"public {signing.public_key(secret).hex()}\n"
            "# Waveband's release signing key, locked with a passphrase. Private: never share or commit it.\n")


def unlock(text: str, passphrase: str) -> bytes:
    """The key in a key file's text. Locked when the passphrase is wrong."""
    fields = dict(line.split(" ", 1) for line in text.splitlines()[1:] if " " in line and not line.startswith("#"))
    try:
        salt, hidden, public = (bytes.fromhex(fields[k].strip()) for k in ("salt", "key", "public"))
        n, r, p = (int(v) for v in fields["cost"].split())
    except (KeyError, ValueError) as exc:
        raise Locked(f"{KEY_PATH} is damaged.") from exc
    mask = _derive(passphrase, salt, n, r, p)
    secret = bytes(a ^ b for a, b in zip(hidden, mask))
    if signing.public_key(secret) != public:
        raise Locked("Wrong passphrase.")
    return secret


def _read() -> str:
    try:
        with open(KEY_PATH, encoding="ascii") as fh:
            return fh.read()
    except FileNotFoundError:
        raise Locked(f"No release key at {KEY_PATH}. Make one with: tools\\release_key.py new") from None
    except OSError as exc:
        # seen 2026-11-16: the file was made by a process run as administrator, in a folder whose
        # permissions let a normal window see it but not open it
        raise Locked(f"The release key at {KEY_PATH} is there but cannot be read ({exc.strerror}). "
                     "Its folder's permissions have to let your own account read it.") from None


def _ask(prompt: str) -> str:
    if not sys.stdin or not sys.stdin.isatty():
        raise Locked("The release key is locked with a passphrase, and this is not a terminal that can ask for "
                     "it. Sign by hand in a terminal: .venv\\Scripts\\python tools\\release_key.py sign <file>")
    return getpass.getpass(prompt)


def _new_passphrase() -> str:
    while True:
        first = _ask(f"New passphrase (at least {_MIN_PASSPHRASE} characters; nothing shows as you type): ")
        if len(first) < _MIN_PASSPHRASE:
            print(f"Too short: give it at least {_MIN_PASSPHRASE} characters.")
            continue
        if _ask("The same again: ") == first:
            return first
        print("They were not the same. Again.")


def _write(text: str) -> None:
    os.makedirs(os.path.dirname(KEY_PATH), exist_ok=True)
    with open(KEY_PATH + ".part", "w", encoding="ascii", newline="\n") as fh:
        fh.write(text)
    os.replace(KEY_PATH + ".part", KEY_PATH)


def is_locked() -> bool:
    """True when the key file is locked with a passphrase (False also when there is none)."""
    try:
        return _read().startswith(_FORMAT)
    except Locked:
        return False


def secret(passphrase: str | None = None) -> bytes:
    """The private key. A locked file asks for its passphrase unless one is given."""
    text = _read()
    if text.startswith(_FORMAT):
        return unlock(text, passphrase if passphrase is not None else _ask("Release key passphrase: "))
    value = bytes.fromhex(text.split("#")[0].strip())  # a plain key file from before 2026-11-16's locking
    if len(value) != 32:
        raise Locked(f"{KEY_PATH} is not a release key.")
    return value


def sign_file(path: str, passphrase: str | None = None) -> str:
    """Write ``path``.sig, the signature of the file's bytes as hex. Returns its path."""
    key = secret(passphrase)
    if signing.public_key(key).hex() != signing.RELEASE_KEY:
        raise Locked("This key is not the one the code trusts (RELEASE_KEY in wwmeter\\signing.py).")
    with open(path, "rb") as fh:
        signature = signing.sign(key, fh.read())
    with open(path + ".sig", "w", encoding="ascii", newline="\n") as fh:
        fh.write(signature.hex() + "\n")
    return path + ".sig"


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else ""
    try:
        if command == "new":
            if os.path.exists(KEY_PATH):
                print(f"There is a key already at {KEY_PATH}. Making another would leave installed copies "
                      "unable to check updates signed with it. Nothing was changed.")
                return 1
            key = signing.new_secret()
            _write(lock(key, _new_passphrase()))
            public = signing.public_key(key).hex()
            with open(CODE, encoding="utf-8") as fh:
                code = fh.read()
            code, n = re.subn(r'^RELEASE_KEY = "[0-9a-f]*"$', f'RELEASE_KEY = "{public}"', code, flags=re.M)
            if n != 1:
                print(f"Couldn't find RELEASE_KEY in {CODE}; put this public key there by hand: {public}")
                return 1
            with open(CODE, "w", encoding="utf-8") as fh:
                fh.write(code)
            print(f"Made the release key, locked with your passphrase: {KEY_PATH}\n"
                  f"Its public half, now in wwmeter\\signing.py: {public}\n"
                  "Keep a copy of the file and the passphrase in a password manager.")
            return 0
        if command in ("protect", "passphrase"):
            text = _read()
            if command == "protect" and text.startswith(_FORMAT):
                print("The key is already locked with a passphrase. To change it: release_key.py passphrase")
                return 1
            key = secret()
            _write(lock(key, _new_passphrase()))
            print(f"{KEY_PATH} is now locked with the new passphrase. Replace the copy in your password "
                  "manager with this file, and delete any other copy of the old one.")
            return 0
        if command == "public":
            print(signing.public_key(secret()).hex())
            return 0
        if command == "sign" and len(argv) > 2:
            print(sign_file(argv[2]))
            return 0
        if command == "verify" and len(argv) > 2:
            with open(argv[2], "rb") as fh:
                data = fh.read()
            with open(argv[2] + ".sig", encoding="ascii") as fh:
                signature = bytes.fromhex(fh.read().strip())
            ok = bool(signing.RELEASE_KEY) and signing.verify(bytes.fromhex(signing.RELEASE_KEY), data, signature)
            print("good signature" if ok else "BAD signature")
            return 0 if ok else 1
    except Locked as why:
        print(why)
        return 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

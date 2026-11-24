"""Fetch the WebView2 SDK and write the COM definitions Waveband's WebView2 overlay uses.

    .venv\\Scripts\\python tools\\make_webview2_com.py

Downloads Microsoft.Web.WebView2 (the version pinned below, checked against its SHA-256) from
nuget.org into a cache folder, then:

- copies ``WebView2Loader.dll`` (x64) and the SDK's ``LICENSE.txt`` into ``lib\\webview2\\``
  (BSD-licensed: the license has to travel with the DLL), and
- writes ``wwmeter\\webview2_com.py``: comtypes interface classes for the interfaces listed in
  ``WANTED`` (and the ones they derive from), read from ``WebView2.h``. The SDK has no type
  library for the core API, so the header's C vtables are the source: each method in order,
  with its parameters.

Run it again only to move to another SDK version; the written module is committed.
``--loader-only`` fetches just the DLL and its license, for a git checkout (``lib\\`` is not
committed); ``run.bat`` does that by itself when the DLL is missing.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION = "1.0.4314.35"
SHA256 = "90778deb1b77e36292828b4b5833c9255c27533f40e0ddd55891ae718944edc4"
URL = f"https://www.nuget.org/api/v2/package/Microsoft.Web.WebView2/{VERSION}"
OUT_MODULE = os.path.join(ROOT, "wwmeter", "webview2_com.py")
OUT_LIB = os.path.join(ROOT, "lib", "webview2")

# What the overlay calls or implements. Base interfaces are added by themselves.
WANTED = (
    "ICoreWebView2Environment3",
    "ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler",
    "ICoreWebView2CreateCoreWebView2CompositionControllerCompletedHandler",
    "ICoreWebView2CompositionController",
    "ICoreWebView2Controller3",
    "ICoreWebView2",
    "ICoreWebView2Settings",
    "ICoreWebView2ExecuteScriptCompletedHandler",
    "ICoreWebView2NavigationCompletedEventHandler",
    "ICoreWebView2NavigationCompletedEventArgs",
    "ICoreWebView2ProcessFailedEventHandler",
    "ICoreWebView2ProcessFailedEventArgs",
)

# C type (as written in the header, pointers stripped) -> ctypes expression
SCALARS = {
    "BOOL": "wintypes.BOOL",
    "UINT32": "ctypes.c_uint32",
    "int": "ctypes.c_int",
    "UINT": "ctypes.c_uint",
    "BYTE": "ctypes.c_ubyte",
    "LONG": "ctypes.c_long",
    "INT32": "ctypes.c_int32",
    "UINT64": "ctypes.c_uint64",
    "INT64": "ctypes.c_int64",
    "ULONG": "ctypes.c_ulong",
    "double": "ctypes.c_double",
    "HRESULT": "HRESULT",
    "HWND": "wintypes.HWND",
    "HCURSOR": "wintypes.HANDLE",
    "HANDLE": "wintypes.HANDLE",
    "RECT": "wintypes.RECT",
    "POINT": "wintypes.POINT",
    "LPCWSTR": "wintypes.LPCWSTR",
    "LPWSTR": "ctypes.c_void_p",  # an out string: freed with CoTaskMemFree, so kept as a pointer
    "COREWEBVIEW2_COLOR": "COREWEBVIEW2_COLOR",
    "EventRegistrationToken": "EventRegistrationToken",
    "IUnknown": "IUnknown",
    "VARIANT": "VARIANT",
}

_VTBL = re.compile(r"typedef struct (\w+)Vtbl\s*\{(.*?)\}\s*\1Vtbl;", re.S)
_METHOD = re.compile(
    r"DECLSPEC_XFGVIRT\((\w+),\s*(\w+)\)\s*(?:/\*[^*]*\*/\s*)?(\w+)\s*\(\s*STDMETHODCALLTYPE\s*\*\s*\w+\s*\)"
    r"\(\s*(.*?)\);",
    re.S,
)
_IID = re.compile(
    r"const IID IID_(\w+) = \{0x([0-9a-f]+),0x([0-9a-f]+),0x([0-9a-f]+),\{((?:0x[0-9a-f]+,?)+)\}\};"
)


def fetch(cache: str) -> str:
    os.makedirs(cache, exist_ok=True)
    path = os.path.join(cache, f"microsoft.web.webview2.{VERSION}.nupkg")
    if not os.path.isfile(path):
        print(f"downloading {URL}")
        with urllib.request.urlopen(URL) as response, open(path + ".part", "wb") as out:
            shutil.copyfileobj(response, out)
        os.replace(path + ".part", path)
    with open(path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    if digest != SHA256:
        os.remove(path)
        raise SystemExit(f"{path}: SHA-256 {digest}, expected {SHA256}; deleted it")
    return path


def iid_text(match: re.Match) -> str:
    a, b, c, rest = match.group(2), match.group(3), match.group(4), match.group(5)
    tail = [int(x, 16) for x in rest.strip(",").split(",")]
    return "{%08X-%04X-%04X-%02X%02X-%s}" % (
        int(a, 16), int(b, 16), int(c, 16), tail[0], tail[1], "".join("%02X" % x for x in tail[2:])
    )


def parse(header: str) -> tuple[dict, dict]:
    """Every interface's methods, in vtable order, as (owner, name, params), and every IID."""
    iids = {m.group(1): iid_text(m) for m in _IID.finditer(header)}
    vtables = {}
    for match in _VTBL.finditer(header):
        methods = []
        for owner, name, _ret, params in _METHOD.findall(match.group(2)):
            args = []
            for raw in params.split(",")[1:]:  # the first is This
                flags = re.findall(r"\[([^\]]*)\]", " ".join(re.findall(r"/\*(.*?)\*/", raw)))
                text = re.sub(r"/\*.*?\*/", " ", raw)
                text = re.sub(r"\b_\w+_\b(\([^)]*\))?", " ", text)  # SAL annotations
                text = text.replace("const ", " ").replace("*", " * ")
                words = text.split()
                stars = words.count("*")
                words = [w for w in words if w != "*"]
                flag_words = ",".join(flags).replace("][", ",")
                args.append((words[0], stars, words[-1], "out" in flag_words, "retval" in flag_words))
            methods.append((owner, name, args))
        vtables[match.group(1)] = methods
    return vtables, iids


def ctype(name: str, stars: int, known: set[str]) -> str:
    if name in known or name == "IUnknown":
        base = name
        stars -= 1  # an interface is always used through a pointer
        expr = f"ctypes.POINTER({base})"
    elif name == "COREWEBVIEW2_PHYSICAL_KEY_STATUS":
        raise SystemExit("COREWEBVIEW2_PHYSICAL_KEY_STATUS is a struct: define it before using it")
    elif name.startswith("COREWEBVIEW2_") and name != "COREWEBVIEW2_COLOR":
        expr = "ctypes.c_int"  # an enum (the header's only other struct is COREWEBVIEW2_COLOR)
    elif name in SCALARS:
        expr = SCALARS[name]
    elif re.match(r"I[A-Z]", name):
        expr = "ctypes.c_void_p"  # an interface the overlay never touches (IStream, ...)
        stars -= 1
    else:
        raise SystemExit(f"no ctypes type for {name!r}: add it to SCALARS")
    for _ in range(stars):
        expr = f"ctypes.POINTER({expr})"
    return expr


def write(vtables: dict, iids: dict) -> None:
    chosen: list[str] = []

    def add(name: str) -> None:
        if name in chosen or name == "IUnknown":
            return
        owners = [owner for owner, _, _ in vtables[name]]
        own_index = owners.index(name)
        base = owners[own_index - 1]
        add(base)
        chosen.append(name)

    for name in WANTED:
        add(name)
    known = set(chosen)
    lines = [
        '"""COM interfaces of WebView2, written by tools/make_webview2_com.py from WebView2.h',
        f'(Microsoft.Web.WebView2 {VERSION}). Do not edit; run the tool again instead."""',
        "",
        "# ruff: noqa",
        "import ctypes",
        "from ctypes import HRESULT, wintypes",
        "",
        "from comtypes import COMMETHOD, GUID, IUnknown",
        "from comtypes.automation import VARIANT",
        "",
        "",
        "class COREWEBVIEW2_COLOR(ctypes.Structure):",
        '    _fields_ = [("A", ctypes.c_ubyte), ("R", ctypes.c_ubyte), ("G", ctypes.c_ubyte), ("B", ctypes.c_ubyte)]',
        "",
        "",
        "class EventRegistrationToken(ctypes.Structure):",
        '    _fields_ = [("value", ctypes.c_int64)]',
        "",
    ]
    for name in chosen:
        owners = [owner for owner, _, _ in vtables[name]]
        base = owners[owners.index(name) - 1]
        lines += ["", f"class {name}({base}):", f'    _iid_ = GUID("{iids[name]}")', ""]
    for name in chosen:
        lines.append(f"{name}._methods_ = [")
        for owner, method, args in vtables[name]:
            if owner != name:
                continue
            parts = [f"[], HRESULT, {method!r}"]
            for c_name, stars, arg, out, retval in args:
                flags = "['out', 'retval']" if retval else ("['out']" if out else "['in']")
                parts.append(f"({flags}, {ctype(c_name, stars, known)}, {arg!r})")
            lines.append("    COMMETHOD(" + ", ".join(parts) + "),")
        lines.append("]")
    lines.append("")
    with open(OUT_MODULE, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    print(f"wrote {OUT_MODULE}: {len(chosen)} interfaces")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", default=os.path.join(ROOT, "TMP", "webview2-sdk"))
    parser.add_argument("--loader-only", action="store_true",
                        help="only fetch WebView2Loader.dll and its license (what run.bat does "
                             "in a git checkout); leave wwmeter\\webview2_com.py as committed")
    args = parser.parse_args()
    package = fetch(args.cache)
    with zipfile.ZipFile(package) as z:
        header = z.read("build/native/include/WebView2.h").decode("utf-8", "replace")
        os.makedirs(OUT_LIB, exist_ok=True)
        for inside, outside in (("build/native/x64/WebView2Loader.dll", "WebView2Loader.dll"),
                                ("LICENSE.txt", "LICENSE.txt")):
            data, path = z.read(inside), os.path.join(OUT_LIB, outside)
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    if f.read() == data:
                        continue  # already there (and a running Waveband may have the DLL loaded)
            with open(path, "wb") as f:
                f.write(data)
    print(f"WebView2Loader.dll and LICENSE.txt are in {OUT_LIB}")
    if args.loader_only:
        return 0
    vtables, iids = parse(header)
    write(vtables, iids)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Put text on the Windows clipboard. Works from any thread and without a window."""

from __future__ import annotations

import time


def copy(text: str) -> None:
    """Raises OSError when the clipboard cannot be had (another program is holding it)."""
    import win32clipboard
    import win32con

    last: Exception | None = None
    for _ in range(5):  # the clipboard is one program's at a time; whoever has it is quick
        try:
            win32clipboard.OpenClipboard()
        except Exception as exc:  # noqa: BLE001 - pywintypes.error, not an OSError
            last = exc
            time.sleep(0.05)
            continue
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
            return
        except Exception as exc:  # noqa: BLE001
            raise OSError(f"could not write to the clipboard: {exc}") from exc
        finally:
            win32clipboard.CloseClipboard()
    raise OSError(f"the clipboard is in use: {last}")

"""Render a page of the running meter to a PNG, in the same web engine the overlay uses.

For checking a change to the overlay's look without the game in front:

    python tools/render_page.py http://127.0.0.1:5055/?view=overlay out.png [width height]
    python tools/render_page.py "http://127.0.0.1:5055/?view=overlay&theme=classic" out.png 440 400

The meter has to be running (``run --demo --no-overlay`` on a spare port will do; set the port in
a config file named by the WWMETER_CONFIG environment variable). ``?view=full`` is the dashboard.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    url, out = argv[1], argv[2]
    width, height = (int(argv[3]), int(argv[4])) if len(argv) > 4 else (440, 400)
    app = QApplication(["render_page"])
    view = QWebEngineView()
    view.setAttribute(Qt.WA_DontShowOnScreen)
    view.page().setBackgroundColor(QColor("#20262e"))  # the overlay itself is transparent
    view.resize(width, height)
    view.setUrl(QUrl(url))
    view.show()

    def grab() -> None:
        print("saved" if view.grab().save(out) else "could not save", out)
        app.quit()

    QTimer.singleShot(6000, grab)  # long enough for the page to connect and draw a state
    app.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

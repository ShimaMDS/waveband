r"""Load a page of a running meter in the overlay's web engine, run steps of JavaScript in it one
after another, print what each gives and save pictures. For checking that the dashboard's
controls still work after a change to it, without the game and without a browser.

    .venv\Scripts\python tools\drive_page.py <url> <steps.js> <picture prefix> [width height]

In the steps file a line "//--- name" starts a step and "//--- name shot" also saves
<prefix>name.png after it. The value of a step's last expression is printed (wrap a list in
JSON.stringify). Steps run 0.9 s apart, which is long enough for the meter to answer one.

tools\settings_walk.js is such a file: it uses every control of the settings page and ends on
the other two pages. It changes settings, so run it against a demo meter with settings of its
own, never the meter in use:

    set WWMETER_CONFIG=<a scratch folder>\config.json     (holding {"port": 5057})
    .venv\Scripts\python -m wwmeter run --demo --no-overlay
    .venv\Scripts\python tools\drive_page.py "http://127.0.0.1:5057/?view=full#settings-keys" tools\settings_walk.js <prefix>
"""
import json
import sys

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

url, steps_path, prefix = sys.argv[1:4]
width, height = (int(sys.argv[4]), int(sys.argv[5])) if len(sys.argv) > 5 else (1280, 800)
steps = []
for line in open(steps_path, encoding="utf-8"):
    if line.startswith("//---"):
        words = line[5:].split()
        steps.append([words[0], "shot" in words[1:], ""])
    elif steps:
        steps[-1][2] += line

app = QApplication(["drive_page"])
view = QWebEngineView()
view.setAttribute(Qt.WA_DontShowOnScreen)
view.page().setBackgroundColor(QColor("#20262e"))
view.resize(width, height)
view.setUrl(QUrl(url))
view.show()
todo = list(steps)


def after(name, shot, value):
    print(f"{name}: {json.dumps(value, ensure_ascii=False)}", flush=True)

    def then():
        if shot:
            view.grab().save(f"{prefix}{name}.png")
        run()

    QTimer.singleShot(900, then)


def run():
    if not todo:
        app.quit()
        return
    name, shot, code = todo.pop(0)
    view.page().runJavaScript(code, lambda value: after(name, shot, value))


QTimer.singleShot(5000, run)
app.exec()

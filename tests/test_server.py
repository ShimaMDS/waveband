import io
import json
import os
import socket
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest import mock

from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

from wwmeter.server import StateServer


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        with open(os.path.join(self.folder.name, "index.html"), "w", encoding="utf-8") as fh:
            fh.write("<p>the meter</p>")
        self.port = free_port()
        self.asked: list[dict] = []
        self.server = StateServer(
            self.port, lambda: {"encounter": None}, self.folder.name, self.on_command, interval=0.05
        )
        self.server.start()

    def tearDown(self):
        self.server.stop()
        self.folder.cleanup()

    def on_command(self, command: dict):
        self.asked.append(command)
        if command.get("cmd") == "settings":
            return {"reply": "settings", "settings": {"theme": "wuwa"}}
        if command.get("cmd") == "boom":
            raise RuntimeError("a command that goes wrong")
        return None

    def get(self, path: str, host: str | None = None) -> tuple[int, bytes]:
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
        if host is not None:
            request.add_header("Host", host)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def socket(self, origin: str | None = None):
        return connect(f"ws://127.0.0.1:{self.port}/ws", origin=origin, open_timeout=5)

    def reply(self, ws) -> dict:
        """The next answer on a connection, past the states pushed in between."""
        for _ in range(100):
            message = json.loads(ws.recv(timeout=5))
            if "reply" in message:
                return message
        self.fail("no answer")

    # -- pages and files ----------------------------------------------------------------------

    def test_the_meters_own_address_is_answered(self):
        self.assertEqual(self.get("/"), (200, b"<p>the meter</p>"))
        self.assertEqual(self.get("/", f"localhost:{self.port}")[0], 200)
        self.assertEqual(self.get("/", f"LOCALHOST:{self.port}")[0], 200)
        status, body = self.get("/state.json")
        self.assertEqual((status, json.loads(body)), (200, {"encounter": None}))

    def test_a_page_reaching_the_meter_under_another_name_is_refused(self):
        # a web site whose name is made to point at 127.0.0.1 asks under its own name
        for host in ("evil.example", f"evil.example:{self.port}", "127.0.0.1", f"127.0.0.1:{self.port + 1}", ""):
            for path in ("/", "/state.json", "/ws"):
                self.assertEqual(self.get(path, host)[0], 403, (host, path))

    def test_files_outside_the_page_folder_are_not_served(self):
        for path in ("/../config.json", "/..%2Fconfig.json", "/nothing.js"):
            self.assertEqual(self.get(path)[0], 404, path)

    # -- the feed -----------------------------------------------------------------------------

    def test_the_meters_pages_and_programs_get_the_feed(self):
        for origin in (None, f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}"):
            with self.socket(origin) as ws:
                self.assertEqual(json.loads(ws.recv(timeout=5)), {"encounter": None}, origin)

    def test_another_sites_page_gets_no_feed(self):
        for origin in ("http://evil.example", f"https://127.0.0.1:{self.port}", "http://127.0.0.1", "null"):
            with self.assertRaises(InvalidStatus, msg=origin) as refused:
                self.socket(origin).close()
            self.assertEqual(refused.exception.response.status_code, 403, origin)
        self.assertEqual(self.asked, [])

    def test_an_answer_goes_to_the_page_that_asked_and_no_other(self):
        with self.socket() as asking, self.socket() as other:
            asking.send(json.dumps({"cmd": "settings"}))
            self.assertEqual(self.reply(asking), {"reply": "settings", "settings": {"theme": "wuwa"}})
            for _ in range(4):
                self.assertNotIn("reply", json.loads(other.recv(timeout=5)))

    def test_a_request_that_goes_wrong_does_not_end_the_feed(self):
        with self.socket() as ws, mock.patch("sys.stderr", io.StringIO()) as said:
            for bad in ("not json", "[1, 2]", json.dumps({"cmd": "boom"}), json.dumps({"cmd": "reset"})):
                ws.send(bad)
            ws.send(json.dumps({"cmd": "settings"}))
            self.assertEqual(self.reply(ws)["reply"], "settings")
            self.assertIn("a command that goes wrong", said.getvalue())
        self.assertEqual([c["cmd"] for c in self.asked], ["boom", "reset", "settings"])


if __name__ == "__main__":
    unittest.main()

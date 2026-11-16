"""Local server: static UI files over HTTP and live state over a WebSocket, on one port.

Bound to 127.0.0.1 only. The overlay window and any browser tab (second monitor, OBS browser
source) connect to the same feed.

Only the meter's own pages are answered. Any web page open in a browser on this PC can ask
127.0.0.1 for things, and the feed carries the settings (the log folder's path among them) and
takes changes to them. So a WebSocket is accepted only from a page this server served (the
Origin header a browser always sends) or from a program that is not a browser (no Origin), and a
request for a file has to name this server as its host, which a page reaching it under another
name does not.
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import sys
import threading
import traceback
from collections.abc import Callable
from http import HTTPStatus

from websockets.asyncio.server import ServerConnection, serve
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

Snapshot = Callable[[], dict]
# What a page asked for. A dict given back is the answer, sent to that page alone with a "reply"
# key in it, which no pushed state has.
Command = Callable[[dict], "dict | None"]


class StateServer:
    def __init__(
        self,
        port: int,
        snapshot: Snapshot,
        ui_dir: str,
        on_command: Command | None = None,
        interval: float = 0.25,
    ) -> None:
        self.port = port
        self._snapshot = snapshot
        self._ui_dir = os.path.abspath(ui_dir)
        self._on_command = on_command
        self._interval = interval
        self._clients: set[ServerConnection] = set()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop: asyncio.Event | None = None
        self.ready = threading.Event()
        self.error: BaseException | None = None
        names = [f"127.0.0.1:{port}", f"localhost:{port}"]
        if port == 80:
            names += ["127.0.0.1", "localhost"]  # a browser leaves the usual port out
        self._hosts = set(names)
        self._origins = [None] + [f"http://{name}" for name in names]

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    # -- http ---------------------------------------------------------------------------------

    def _static(self, path: str) -> Response:
        rel = path.split("?", 1)[0].lstrip("/") or "index.html"
        full = os.path.abspath(os.path.join(self._ui_dir, rel))
        if not full.startswith(self._ui_dir + os.sep) or not os.path.isfile(full):
            return self._respond(HTTPStatus.NOT_FOUND, b"not found", "text/plain")
        with open(full, "rb") as fh:
            body = fh.read()
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith(("javascript", "json")):
            ctype += "; charset=utf-8"
        return self._respond(HTTPStatus.OK, body, ctype)

    @staticmethod
    def _respond(status: HTTPStatus, body: bytes, ctype: str) -> Response:
        headers = Headers(
            {"Content-Type": ctype, "Content-Length": str(len(body)), "Cache-Control": "no-store"}
        )
        return Response(status.value, status.phrase, headers, body)

    def _process_request(self, connection: ServerConnection, request: Request) -> Response | None:
        path = request.path.split("?", 1)[0]
        try:
            host = (request.headers.get("Host") or "").strip().lower()
        except Exception:  # noqa: BLE001 - more than one Host header
            host = ""
        if host not in self._hosts:
            return self._respond(HTTPStatus.FORBIDDEN, b"not the meter's own address", "text/plain")
        if path == "/ws":
            return None  # continue with the WebSocket handshake
        if path == "/state.json":
            body = json.dumps(self._snapshot(), ensure_ascii=False).encode("utf-8")
            return self._respond(HTTPStatus.OK, body, "application/json; charset=utf-8")
        return self._static(request.path)

    # -- websocket ----------------------------------------------------------------------------

    async def _handle(self, connection: ServerConnection) -> None:
        self._clients.add(connection)
        try:
            async for message in connection:
                if self._on_command is None:
                    continue
                try:
                    command = json.loads(message)
                except ValueError:
                    continue
                if not isinstance(command, dict):
                    continue
                try:
                    reply = self._on_command(command)
                except Exception:  # noqa: BLE001 - one bad request must not end the feed
                    traceback.print_exc(file=sys.stderr)
                    continue
                if isinstance(reply, dict):
                    await connection.send(json.dumps(reply, ensure_ascii=False))
        except ConnectionClosed:
            pass
        finally:
            self._clients.discard(connection)

    async def _broadcast(self) -> None:
        assert self._stop is not None
        while not self._stop.is_set():
            if self._clients:
                payload = json.dumps(self._snapshot(), ensure_ascii=False)
                for client in list(self._clients):
                    try:
                        await client.send(payload)
                    except ConnectionClosed:
                        self._clients.discard(client)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                pass

    async def _main(self) -> None:
        self._stop = asyncio.Event()
        async with serve(
            self._handle, "127.0.0.1", self.port, process_request=self._process_request,
            origins=self._origins,
        ):
            self.ready.set()
            await self._broadcast()

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        try:
            self._loop.run_until_complete(self._main())
        except BaseException as exc:  # noqa: BLE001 - surfaced to the starter through .error
            self.error = exc
            self.ready.set()
        finally:
            self._loop.close()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="state-server", daemon=True)
        self._thread.start()
        self.ready.wait(timeout=10)
        if self.error is not None:
            raise RuntimeError(f"could not start server on port {self.port}: {self.error}") from self.error

    def stop(self) -> None:
        if self._loop is not None and self._stop is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
        if self._thread is not None:
            self._thread.join(timeout=5)

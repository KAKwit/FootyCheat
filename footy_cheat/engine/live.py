import http.client
import json
from collections.abc import Callable

from .parse import user_agent


class LiveSession:
    def __init__(self) -> None:
        self.stop = False
        self._conn: http.client.HTTPSConnection | None = None

    def run(self, email: str, on_payload: Callable[[object], None]) -> None:
        self._close_conn()
        conn = http.client.HTTPSConnection("sse.squiggle.com.au", timeout=30)
        self._conn = conn
        try:
            conn.request(
                "GET",
                "/games",
                headers={
                    "User-Agent": user_agent(email),
                    "Accept": "text/event-stream",
                },
            )
            response = conn.getresponse()
            if response.status < 200 or response.status >= 300:
                raise RuntimeError(f"Live scores returned {response.status}")
            if conn.sock is not None:
                conn.sock.settimeout(None)
            pending = ""
            data = ""
            while not self.stop:
                chunk = response.readline()
                if not chunk:
                    break
                text = pending + chunk.decode("utf-8", errors="replace")
                lines = text.split("\n")
                pending = ""
                if not text.endswith("\n"):
                    pending = lines.pop()
                for raw in lines:
                    line = raw[:-1] if raw.endswith("\r") else raw
                    if line == "":
                        if data:
                            try:
                                on_payload(json.loads(data))
                            except json.JSONDecodeError:
                                pass
                        data = ""
                        continue
                    if line.startswith("data:"):
                        data += line[5:].strip()
        finally:
            if self._conn is conn:
                self._close_conn()

    def close(self) -> None:
        self.stop = True
        self._close_conn()

    def _close_conn(self) -> None:
        conn = self._conn
        self._conn = None
        if conn is None:
            return
        try:
            conn.close()
        except Exception:
            pass

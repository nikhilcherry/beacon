"""Core relay: an in-memory pub/sub bus exposed over plain HTTP + SSE.

No websockets, no external dependencies. Publishing is a POST, subscribing
is a GET that streams Server-Sent Events -- both are trivial to speak from
a browser (fetch + EventSource), a phone, an ESP32, or curl.
"""

from __future__ import annotations

import json
import threading
import time
import queue
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from urllib.parse import urlparse, parse_qs

FIREHOSE = "_all"  # special channel name: dashboard subscribes here to see everything


class Bus:
    """Thread-safe channel registry. One Queue per subscriber connection."""

    def __init__(self):
        self._lock = threading.Lock()
        self._subscribers = {}  # channel -> {sub_id: Queue}
        self._presence = {}     # channel -> {sub_id: {"name": str, "joined": float}}

    def subscribe(self, channel: str, name: str | None = None):
        sub_id = uuid.uuid4().hex[:8]
        q = queue.Queue()
        with self._lock:
            self._subscribers.setdefault(channel, {})[sub_id] = q
            self._presence.setdefault(channel, {})[sub_id] = {
                "name": name or sub_id,
                "joined": time.time(),
            }
        self._broadcast_system(channel, "join", name or sub_id)
        return sub_id, q

    def unsubscribe(self, channel: str, sub_id: str):
        with self._lock:
            self._subscribers.get(channel, {}).pop(sub_id, None)
            info = self._presence.get(channel, {}).pop(sub_id, None)
        self._broadcast_system(channel, "leave", info["name"] if info else sub_id)

    def publish(self, channel: str, payload: dict):
        event = {
            "channel": channel,
            "type": "message",
            "data": payload,
            "ts": time.time(),
        }
        self._deliver(channel, event)
        if channel != FIREHOSE:
            self._deliver(FIREHOSE, event)

    def _broadcast_system(self, channel: str, kind: str, who: str):
        event = {
            "channel": channel,
            "type": kind,
            "data": {"who": who, "count": self.count(channel)},
            "ts": time.time(),
        }
        self._deliver(channel, event)
        if channel != FIREHOSE:
            self._deliver(FIREHOSE, event)

    def _deliver(self, channel: str, event: dict):
        with self._lock:
            subs = list(self._subscribers.get(channel, {}).values())
        for q in subs:
            q.put(event)

    def count(self, channel: str) -> int:
        with self._lock:
            return len(self._subscribers.get(channel, {}))

    def snapshot(self) -> dict:
        with self._lock:
            return {
                ch: {
                    "subscribers": len(subs),
                    "names": [self._presence[ch][sid]["name"] for sid in subs],
                }
                for ch, subs in self._subscribers.items()
                if ch != FIREHOSE and subs
            }


class Handler(BaseHTTPRequestHandler):
    bus: Bus = None  # set by make_server
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # keep demo output quiet; use --verbose flag hook if ever needed

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _cors_preflight(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_OPTIONS(self):
        self._cors_preflight()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path == "/" or path == "/index.html":
            return self._serve_dashboard()
        if path == "/health":
            return self._send_json({"ok": True})
        if path == "/channels":
            return self._send_json(self.bus.snapshot())
        if path.startswith("/sub/"):
            channel = path[len("/sub/"):] or FIREHOSE
            name = (qs.get("name") or [None])[0]
            return self._stream(channel, name)

        self._send_json({"error": "not found"}, status=404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if not path.startswith("/pub/"):
            return self._send_json({"error": "not found"}, status=404)

        channel = path[len("/pub/"):]
        if not channel:
            return self._send_json({"error": "channel required"}, status=400)

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return self._send_json({"error": "invalid json"}, status=400)

        self.bus.publish(channel, payload)
        self._send_json({"ok": True, "channel": channel})

    def _serve_dashboard(self):
        html = resources.files("beacon").joinpath("dashboard.html").read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def _stream(self, channel, name):
        sub_id, q = self.bus.subscribe(channel, name)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            while True:
                try:
                    event = q.get(timeout=15)
                    chunk = f"data: {json.dumps(event)}\n\n".encode()
                except queue.Empty:
                    chunk = b": keepalive\n\n"
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.bus.unsubscribe(channel, sub_id)


def make_server(host: str, port: int) -> ThreadingHTTPServer:
    bus = Bus()

    class BoundHandler(Handler):
        pass

    BoundHandler.bus = bus
    server = ThreadingHTTPServer((host, port), BoundHandler)
    server.daemon_threads = True
    server.bus = bus
    return server

import json
import queue
import threading
import time
import urllib.request

import pytest

from beacon.server import make_server


@pytest.fixture
def server():
    srv = make_server("127.0.0.1", 0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.15)
    yield srv
    srv.shutdown()


def _port(server):
    return server.server_address[1]


def test_health(server):
    port = _port(server)
    resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/health")
    assert resp.status == 200
    assert json.loads(resp.read()) == {"ok": True}


def test_dashboard_serves_html(server):
    port = _port(server)
    resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/")
    assert resp.status == 200
    assert b"beacon" in resp.read()


def test_publish_requires_channel(server):
    port = _port(server)
    req = urllib.request.Request(f"http://127.0.0.1:{port}/pub/", method="POST", data=b"{}")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 400


def test_subscribe_receives_published_message(server):
    port = _port(server)
    results = queue.Queue()

    def subscriber():
        resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/sub/room?name=bob")
        for raw in resp:
            line = raw.decode().strip()
            if line.startswith("data:"):
                event = json.loads(line[len("data:"):].strip())
                results.put(event)
                if event["type"] == "message":
                    return

    t = threading.Thread(target=subscriber, daemon=True)
    t.start()
    time.sleep(0.2)

    join_event = results.get(timeout=2)
    assert join_event["type"] == "join"
    assert join_event["data"]["who"] == "bob"

    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/pub/room",
        data=json.dumps({"hello": "world"}).encode(),
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req)

    message_event = results.get(timeout=2)
    assert message_event["type"] == "message"
    assert message_event["data"] == {"hello": "world"}


def test_channels_snapshot_reflects_active_subscribers(server):
    port = _port(server)

    def subscriber():
        resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/sub/lobby?name=alice")
        for _ in resp:
            break

    t = threading.Thread(target=subscriber, daemon=True)
    t.start()
    time.sleep(0.2)

    resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/channels")
    data = json.loads(resp.read())
    assert data["lobby"]["subscribers"] == 1
    assert data["lobby"]["names"] == ["alice"]


def test_firehose_receives_all_channel_traffic(server):
    port = _port(server)
    results = queue.Queue()

    def subscriber():
        resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/sub/_all?name=watcher")
        for raw in resp:
            line = raw.decode().strip()
            if line.startswith("data:"):
                event = json.loads(line[len("data:"):].strip())
                results.put(event)
                if event["type"] == "message":
                    return

    t = threading.Thread(target=subscriber, daemon=True)
    t.start()
    time.sleep(0.2)
    results.get(timeout=2)  # join event for the watcher itself

    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/pub/anything",
        data=json.dumps({"n": 1}).encode(),
    )
    urllib.request.urlopen(req)

    event = results.get(timeout=2)
    assert event["channel"] == "anything"
    assert event["data"] == {"n": 1}

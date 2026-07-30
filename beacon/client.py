"""Minimal client for scripts, IoT devices, or anything with urllib.

    from beacon.client import BeaconClient

    c = BeaconClient("http://localhost:8420", "sensors")
    c.publish({"temp": 21.4})

    for event in c.subscribe():
        print(event)
"""

from __future__ import annotations

import json
import urllib.request


class BeaconClient:
    def __init__(self, base_url: str, channel: str):
        self.base_url = base_url.rstrip("/")
        self.channel = channel

    def publish(self, data: dict):
        url = f"{self.base_url}/pub/{self.channel}"
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())

    def subscribe(self, name: str | None = None):
        url = f"{self.base_url}/sub/{self.channel}"
        if name:
            url += f"?name={name}"
        with urllib.request.urlopen(url) as resp:
            for raw_line in resp:
                line = raw_line.decode().strip()
                if line.startswith("data:"):
                    yield json.loads(line[len("data:"):].strip())

# beacon

**One command turns any laptop into a real-time pub/sub relay** — with a
live dashboard and, if you want, a public URL. No websocket library, no
build step, no account to sign up for.

```bash
pip install -e .          # or: pip install beacon-relay, once published
beacon serve
```

```
beacon relay listening on http://localhost:8420
  dashboard : http://localhost:8420/
  publish   : POST http://localhost:8420/pub/<channel>   (JSON body)
  subscribe : GET  http://localhost:8420/sub/<channel>   (Server-Sent Events)
```

Open `http://localhost:8420/` and you'll see every channel and every message
flowing through the relay, live, as it happens.

## Why

Every hackathon project that needs two devices to talk to each other in
real time ends up hand-rolling the same plumbing: a websocket server, a
message format, reconnect logic, a way to see it's actually working. That's
an hour you don't have, spent before you've built anything a judge cares
about.

`beacon` is that hour, already spent. Point every device at one relay and
you get:

- **pub/sub over plain HTTP** — publish is a `POST`, subscribe is a `GET`
  that streams [Server-Sent Events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events).
  Every browser, phone, microcontroller, and `curl` already speaks this —
  no client library to install.
- **a live dashboard** — every channel, every message, every join/leave,
  visible the moment it happens. Great for judges: point at the screen and
  say "look, it's live."
- **presence for free** — subscribers can pass `?name=you`, and everyone
  else on the channel sees you join and leave.
- **one flag for a public URL** — `beacon serve --tunnel` shells out to a
  [cloudflared quick tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/)
  and prints a `*.trycloudflare.com` URL. No DNS, no account, no config —
  point two phones at it from across the room.
- **zero dependencies** — pure Python standard library. Works on a
  conference laptop with no internet (besides `--tunnel`, which needs
  `cloudflared` on your `PATH`).

This is the realtime half of what [`hoist`](https://github.com/nikhilcherry/hoist)
does for static apps: `hoist` gets a whole app onto a public URL; `beacon`
gets many devices talking to each other in real time, in about the same
amount of typing.

## Use it for

- **multiplayer state** — every player publishes to a shared channel,
  everyone else subscribes. See `examples/multiplayer_cursors.html` for a
  ~40-line working demo: open it in two browser tabs, move your mouse,
  watch the other tab's cursor follow.
- **IoT / sensor swarms** — an ESP32, a Raspberry Pi, a phone's
  accelerometer, all `POST`ing to `/pub/sensors`; one dashboard watching
  all of them.
- **live leaderboards / scoreboards** — publish a score update, every
  connected screen updates instantly.
- **cross-device control** — a phone as a remote for a laptop app, a QR
  code that opens a controller page that publishes button presses.
- **judge-visible "it's alive" proof** — the dashboard alone is often worth
  running just so judges can see live traffic during a demo.

## API

| Method | Path              | Does                                                    |
|--------|-------------------|----------------------------------------------------------|
| `POST` | `/pub/<channel>`  | Publish a JSON body to `<channel>`                        |
| `GET`  | `/sub/<channel>`  | Subscribe via Server-Sent Events (add `?name=you` for presence) |
| `GET`  | `/sub/_all`       | Firehose: every event on every channel (what the dashboard uses) |
| `GET`  | `/channels`       | JSON snapshot of active channels and their subscribers    |
| `GET`  | `/health`         | Liveness check                                            |
| `GET`  | `/`               | The live dashboard                                        |

### From the browser

```js
// publish
fetch("http://localhost:8420/pub/sensors", {
  method: "POST",
  body: JSON.stringify({ temp: 21.4 }),
});

// subscribe
const source = new EventSource("http://localhost:8420/sub/sensors?name=laptop");
source.onmessage = (e) => console.log(JSON.parse(e.data));
```

### From Python

```python
from beacon.client import BeaconClient

c = BeaconClient("http://localhost:8420", "sensors")
c.publish({"temp": 21.4})

for event in c.subscribe(name="pi-zero"):
    print(event)
```

### From the command line

```bash
beacon pub sensors '{"temp": 21.4}'
beacon sub sensors
```

## Going public

```bash
beacon serve --tunnel
```

```
  public    : https://random-words-here.trycloudflare.com  <-- share this
```

That URL works from any device, anywhere — perfect for handing to a judge's
phone or letting teammates on a different network publish/subscribe. It's an
ephemeral tunnel: it dies when `beacon` stops, and needs nothing configured
ahead of time (unlike `hoist`, which sets up a persistent tunnel with your
own domain — reach for that when the app needs to outlive the demo).

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
pytest tests/ -v
```

## License

MIT

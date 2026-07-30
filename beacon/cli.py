"""beacon CLI: `beacon serve`, `beacon pub`, `beacon sub`."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

from .server import make_server

DEFAULT_PORT = 8420


def cmd_serve(args):
    server = make_server(args.host, args.port)
    url = f"http://{args.host if args.host != '0.0.0.0' else 'localhost'}:{args.port}"
    print(f"beacon relay listening on {url}")
    print(f"  dashboard : {url}/")
    print(f"  publish   : POST {url}/pub/<channel>   (JSON body)")
    print(f"  subscribe : GET  {url}/sub/<channel>   (Server-Sent Events)")

    tunnel_proc = None
    if args.tunnel:
        tunnel_proc = _start_tunnel(args.port)  # runs concurrently, never blocks serving
    elif args.hoist:
        _start_hoist(args.hoist, args.port)  # runs concurrently, never blocks serving

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        if tunnel_proc:
            tunnel_proc.terminate()
        if args.hoist:
            print(f"  note      : public URL still live under hoist -- "
                  f"run 'hoist down {args.hoist}' to remove it")


def _start_tunnel(port: int):
    if not shutil.which("cloudflared"):
        print("  public    : skipped (cloudflared not found on PATH -- "
              "install it to use --tunnel)")
        return None

    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"http://localhost:{port}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    def watch():
        pattern = re.compile(r"https://[a-zA-Z0-9.-]+trycloudflare\.com")
        for _ in range(200):
            line = proc.stdout.readline()
            if not line:
                break
            match = pattern.search(line)
            if match:
                print(f"  public    : {match.group(0)}  <-- share this")
                break

    # cloudflared can take a few seconds to establish the tunnel and print its
    # URL; watch for it on a background thread so the relay starts serving
    # (and the dashboard/API are reachable) immediately.
    threading.Thread(target=watch, daemon=True).start()
    return proc


def _wait_until_ready(port: int, attempts: int = 50, delay: float = 0.1) -> bool:
    """Poll /health until the relay is actually accepting connections."""
    for _ in range(attempts):
        try:
            urllib.request.urlopen(f"http://localhost:{port}/health", timeout=1)
            return True
        except (urllib.error.URLError, ConnectionError):
            time.sleep(delay)
    return False


def _start_hoist(name: str, port: int):
    """Give the relay a stable public URL via `hoist adopt`, if hoist is set up.

    Unlike --tunnel's cloudflared quick tunnel (random URL, dies with the
    process), `hoist adopt` registers the port under your own persistent
    Cloudflare Tunnel + DNS -- the same URL every time you run `beacon
    serve --hoist`, which is what you want for a QR code left up for a
    whole hackathon rather than a one-off demo link.
    """
    if not shutil.which("hoist"):
        print("  public    : skipped ('hoist' not found on PATH -- "
              "https://github.com/nikhilcherry/hoist, or use --tunnel "
              "for a one-off link instead)")
        return

    def run():
        if not _wait_until_ready(port):
            print("  public    : skipped (relay never became ready for hoist adopt)")
            return
        subprocess.run(["hoist", "adopt", name, "--port", str(port)])

    # `hoist adopt` is a one-shot call (it writes an ingress rule and
    # returns; it doesn't stay running), but it needs the local port to
    # already be accepting connections -- run it on a background thread so
    # cmd_serve can go straight into server.serve_forever() without waiting.
    threading.Thread(target=run, daemon=True).start()


def cmd_pub(args):
    url = f"http://{args.host}:{args.port}/pub/{args.channel}"
    try:
        payload = json.loads(args.data) if args.data else {}
    except json.JSONDecodeError:
        payload = {"message": args.data}
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        print(resp.read().decode())


def cmd_sub(args):
    url = f"http://{args.host}:{args.port}/sub/{args.channel}"
    print(f"listening on {args.channel} (ctrl-c to stop)")
    with urllib.request.urlopen(url) as resp:
        for raw_line in resp:
            line = raw_line.decode().strip()
            if line.startswith("data:"):
                print(line[len("data:"):].strip())


def main(argv=None):
    parser = argparse.ArgumentParser(prog="beacon", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="start the relay server")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    public = serve.add_mutually_exclusive_group()
    public.add_argument("--tunnel", action="store_true",
                         help="expose a public URL via a cloudflared quick tunnel "
                              "(random, one-off -- dies when beacon stops)")
    public.add_argument("--hoist", nargs="?", const="beacon", default=None, metavar="NAME",
                         help="expose a public URL via 'hoist adopt' (stable, reuses your "
                              "own domain -- persists across restarts). Defaults to the "
                              "name 'beacon' if no NAME is given.")
    serve.set_defaults(func=cmd_serve)

    pub = sub.add_parser("pub", help="publish one message from the command line")
    pub.add_argument("channel")
    pub.add_argument("data", nargs="?", default="{}", help="JSON payload (or plain text)")
    pub.add_argument("--host", default="localhost")
    pub.add_argument("--port", type=int, default=DEFAULT_PORT)
    pub.set_defaults(func=cmd_pub)

    sub_cmd = sub.add_parser("sub", help="tail a channel from the command line")
    sub_cmd.add_argument("channel")
    sub_cmd.add_argument("--host", default="localhost")
    sub_cmd.add_argument("--port", type=int, default=DEFAULT_PORT)
    sub_cmd.set_defaults(func=cmd_sub)

    # stdout is fully buffered (not line-buffered) when piped or redirected --
    # e.g. under systemd, or `beacon serve > log.txt &` -- so without this the
    # startup banner and tunnel URL can sit invisible until the process exits.
    sys.stdout.reconfigure(line_buffering=True)

    parsed = parser.parse_args(argv)
    parsed.func(parsed)


if __name__ == "__main__":
    sys.exit(main())

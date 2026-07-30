# Implementation Plan: beacon <-> hoist integration

## Task Type
- [ ] Frontend
- [x] Backend
- [ ] Fullstack

(No multi-model runtime available — this plan was produced by Claude alone,
not the Codex/Gemini dual-analysis this command normally runs.)

## Context found

- `beacon serve --tunnel` (`beacon/cli.py:_start_tunnel`) shells out to
  `cloudflared tunnel --url http://localhost:<port>` directly. This gives a
  random `*.trycloudflare.com` URL that changes every run and dies with the
  process — fine for a one-off demo, bad for anything you want to point at
  repeatedly (a QR code taped to a table for a whole hackathon, a webhook
  target, teammates bookmarking a URL).
- `hoist` (`~/Projects/hoist/hoist/cli.py:556`) already has the exact
  primitive this needs: `hoist adopt <name> --port <port> [--domain
  --hostname] [--no-qr]` — it exposes an **already-running** local port
  under hoist's persistent Cloudflare Tunnel + DNS + systemd config, and
  prints a URL + QR code (`cmd_adopt`, `hoist/cli.py:~183` area). Unlike
  `hoist up`, `adopt` does not manage the process lifecycle — it assumes
  the port is independently running, which matches beacon exactly.
- `hoist down <name>` removes the ingress rule later; hoist treats up/down
  as explicit, not tied to the adopted process's lifetime.

## Technical Solution

Add a second, alternative way for `beacon serve` to go public: instead of
(or in addition to) its own ephemeral quick tunnel, shell out to `hoist
adopt` when `hoist` is on `PATH`. This reuses your already-configured
domain and gives beacon a stable, memorable URL (e.g.
`relay.premortem.tech`) that survives restarts, instead of a fresh random
string every run. Keep `--tunnel` for the "no hoist installed / just want a
quick one-off link" case — the two are complementary, not a replacement.

## Implementation Steps

1. **Add `--hoist [NAME]` flag to `beacon serve`** (`beacon/cli.py`,
   `main()`'s `serve` subparser) — `nargs="?"`, `const="beacon"`, default
   `None`, so `--hoist` alone defaults the app name to `beacon` and
   `--hoist myrelay` lets you name it. Make `--tunnel` and `--hoist`
   mutually exclusive via `argparse`'s `add_mutually_exclusive_group()` —
   they're two different answers to "how do I get a public URL," and
   running both would start two competing cloudflared processes.

2. **Add `_start_hoist(name, port)` in `beacon/cli.py`**, parallel to the
   existing `_start_tunnel`:
   - `shutil.which("hoist")` check first; if missing, print a one-line
     hint ("install hoist for a persistent URL: <link>, or use --tunnel
     for a one-off") and fall through to serving locally only — same
     graceful-degradation pattern `_start_tunnel` already uses for missing
     `cloudflared`.
   - Run `hoist adopt <name> --port <port>` as a **foreground-ish**
     subprocess with inherited stdout (not captured/parsed like the
     tunnel-URL regex match) — hoist already prints a nice URL + QR code
     itself; no need to reimplement that. Just let its output pass
     through directly.
   - Since `hoist adopt` is a one-shot CLI call (it writes the ingress
     rule and returns; it doesn't stay running), call it once at startup
     via `subprocess.run(...)`, not `Popen` — no background thread needed
     here, unlike the tunnel case. This should happen *after*
     `server.serve_forever()` would start, i.e. spawn a thread that does
     "wait until the local server is accepting connections, then call
     hoist adopt" — in practice a short fixed delay (~200ms) or a quick
     retry-loop against `/health` is enough, since binding already
     happens synchronously in `make_server()`.
   - On clean shutdown (Ctrl-C), do **not** auto-run `hoist down` — print
     a reminder instead (`"public URL still live under hoist -- run
     'hoist down <name>' to remove it"`). This matches hoist's own
     explicit up/down philosophy from the README rather than silently
     tearing down infrastructure the user may want to keep across
     restarts of the relay.

3. **Update `README.md` "Going public" section** to document `--hoist` as
   the option for a stable/reusable URL, keeping `--tunnel` documented as
   the ephemeral option. Make the tradeoff explicit in one line each so a
   reader picks correctly without needing to know hoist's internals.

4. **Tests** (`tests/test_server.py` or a new `tests/test_cli.py`):
   - Unit-test `_start_hoist` with `shutil.which` mocked to `None` -> hint
     printed, no exception, returns cleanly (mirrors the existing
     "cloudflared missing" test gap — there isn't one yet for `_start_tunnel`
     either; add both while touching this code).
   - Do **not** attempt to actually invoke a real `hoist` binary in CI
     (GitHub Actions runners won't have it, no Cloudflare Tunnel
     configured) — mock `subprocess.run`/`shutil.which` instead.

5. **No changes to the `hoist` repo itself.** `adopt` already does
   everything needed; this integration lives entirely on beacon's side as
   a consumer of hoist's existing CLI, so `hoist`'s tested/released code
   stays untouched.

## Key Files

| File | Operation | Description |
|------|-----------|--------------|
| `beacon/cli.py` | Modify | Add `--hoist` flag, `_start_hoist()`, mutually-exclusive with `--tunnel` |
| `README.md` | Modify | Document `--hoist` vs `--tunnel` tradeoff in "Going public" |
| `tests/test_cli.py` | Add | Mock-based tests for `_start_hoist` graceful degradation |

## Risks and Mitigation

| Risk | Mitigation |
|------|------------|
| Two tunnels racing if both `--tunnel` and `--hoist` are passed | `argparse` mutually exclusive group — invalid combination fails at parse time, before any subprocess spawns |
| `hoist adopt` called before the local port is actually accepting connections | Short retry-loop against `/health` before calling `hoist adopt`, instead of a blind fixed sleep |
| User forgets an adopted relay is still publicly routable after stopping beacon | Print an explicit `hoist down <name>` reminder on shutdown instead of silently doing nothing (and instead of silently auto-removing it, which could surprise someone relying on it staying up) |
| `hoist` not installed | Same graceful-degradation pattern as the existing `cloudflared` check — hint and continue, never a hard crash |

### SESSION_ID (for /ccg:execute use)
- CODEX_SESSION: n/a (ccg-workflow runtime not installed this session)
- GEMINI_SESSION: n/a (ccg-workflow runtime not installed this session)

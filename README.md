# Cruze

A private, adults-only random video chat prototype. Browser media uses direct WebRTC connections, with STUN discovery and **no TURN relay fallback**. A Python/aiohttp server serves the interface and handles matchmaking and signaling. No Node.js build step is required.

## Run locally

Install Python 3.11+ and [uv](https://docs.astral.sh/uv/), then:

```sh
uv sync
uv run python server.py
```

Open http://localhost:8000 in two separate browser windows, confirm you are 18 or older in the popup, and click **Start** in both. Allow camera and microphone access. Headphones prevent audio feedback. Skip prefers pairs that have never skipped each other, then older skipped pairs, with the most recently skipped pair last. Equal priorities follow queue order. If only two people are waiting, they match again immediately. Only waiting users are considered; active calls are not interrupted. Skip history is shared by each pair and lasts for their WebSocket sessions, clearing on disconnect or server restart.

## Included

- In-memory waiting queue and one-to-one matching.
- Offers, answers, and ICE candidates scoped to a unique match ID.
- Direct video/audio, local preview, microphone mute, camera toggle.
- Start/Skip, Stop, disconnect cleanup, and 15-second setup timeout.
- Same-origin WebSocket validation, payload limits, and per-socket message/skip limits.
- Full-screen video with a floating control bar and icon-only camera/microphone toggles.
- First-visit 18+ confirmation, remembered in a `cruze_adult` cookie for 365 days (SameSite=Lax; Secure on HTTPS). No camera access until Start is clicked.

The server holds no accounts or persistent conversation history, and does not receive or record media. It does see signaling metadata (including ICE addresses). Public STUN discovery currently uses `stun.l.google.com:19302`; change the STUN-only configuration in `static/app.js` if needed. STUN receives network discovery requests, not video. Partners can learn each other’s public connection IP addresses and may record locally.

## Testing

```sh
uv run pytest -q
uv run playwright install chromium
# With the server running in another terminal:
uv run python tests/browser_smoke.py
```

Integration tests cover pairing, signaling isolation, skipping, disconnection, origin checks, and asset restrictions. The browser smoke test uses simulated cameras in independent Chromium contexts, checks received video and selected non-relay candidate pairs, controls, cleanup, responsive layout, and connection failure. Screenshots are saved to `/tmp/cruze-desktop.png` and `/tmp/cruze-mobile.png`.

Before relying on real-world connectivity, manually test different home networks, mobile data, restrictive networks, Safari, and Firefox. Same-machine browser tests do not establish cross-network success rates. With no relay, some combinations simply cannot connect.

## Deployment boundaries

The default binds to `127.0.0.1:8000`. Set `HOST` and `PORT` to change this. Browser camera access requires HTTPS outside localhost. For an HTTPS reverse proxy, preserve the Host header, forward WebSocket upgrades, and set `CRUZE_ORIGIN=https://your-host.example` to the exact browser origin. Run one server process: queue state is not shared between workers and resets on restart.

This is a **private prototype, not a public adult platform**. The remembered 18+ declaration is not verified age assurance or access control. Keep testing local or behind an external access gate. Reporting/blocking, moderation and incident workflows, appropriate age assurance, global abuse controls, and jurisdiction-specific review remain public-launch work. Camera-off disables the video track; Stop releases all local media tracks.

## Files

- `server.py` — static files, WebSocket protocol, queue and match lifecycle.
- `static/app.js` — camera lifecycle, WebRTC, UI state.
- `static/index.html`, `static/style.css` — interface.
- `tests/` — signaling integration and browser smoke tests.

## 1f517 server deployment

Cruze lives at `/srv/cruze` on `54.37.204.161`, with the `cruze` systemd service listening on `127.0.0.1:8774`. Caddy routes `cruze.cc` through `/etc/caddy/sites/cruze.caddy`, imported by its main configuration. The service uses an isolated dynamic user, a read-only filesystem, and restarts on failure or server reboot.

Redeploy the working tree with `./deploy/deploy.sh`. It transfers only the server, static assets, and deployment files, installs hash-locked runtime dependencies, checks the backend, validates Caddy, and reloads the proxy. The main Caddyfile is backed up before modification. DNS requires an A record for `cruze.cc` pointing to `54.37.204.161` (DNS only); Caddy obtains and renews HTTPS certificates automatically.

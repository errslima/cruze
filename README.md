# Cruze

A private, adults-only random video chat prototype. Browser media uses direct WebRTC connections, with STUN discovery and **no TURN relay fallback**. A Python/aiohttp server serves the interface and handles matchmaking and signaling. No Node.js build step is required.

## Run locally

Install Python 3.11+ and [uv](https://docs.astral.sh/uv/), then:

```sh
uv sync
uv run python server.py
```

Open http://localhost:8000 in two separate browser windows, confirm the private-test notice, and click **Start chatting** in both. Allow camera and microphone access. Headphones prevent audio feedback. A third participant lets you test Next: the last partner is excluded from immediate rematching, so two users who skip each other will wait for somebody else.

## Included

- In-memory waiting queue and one-to-one matching.
- Offers, answers, and ICE candidates scoped to a unique match ID.
- Direct video/audio, local preview, microphone mute, camera toggle.
- Next, Stop, disconnect cleanup, and 15-second setup timeout.
- Same-origin WebSocket validation, payload limits, and per-socket message/skip limits.
- Responsive interface with explicit connection states.

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

This is a **private prototype, not a public adult platform**. The 18+ checkbox is a notice, not verified age assurance or access control. Keep testing local or behind an external access gate. Reporting/blocking, moderation and incident workflows, appropriate age assurance, global abuse controls, and jurisdiction-specific review remain public-launch work. Camera-off disables the video track; Stop releases all local media tracks.

## Files

- `server.py` — static files, WebSocket protocol, queue and match lifecycle.
- `static/app.js` — camera lifecycle, WebRTC, UI state.
- `static/index.html`, `static/style.css` — interface.
- `tests/` — signaling integration and browser smoke tests.

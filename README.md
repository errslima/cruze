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
- Webcam dropdown beside the camera toggle; switches during a call and remembers the selected device in this browser. Camera names become available after permission is granted.
- Start/Skip, Stop, disconnect cleanup, and 15-second setup timeout.
- Block with confirmation: excludes the partner’s IP address and stores each block for one year in a browser cookie. Blocks override skip priorities, including when only two users are available. Clearing cookies removes saved blocks; IP changes and shared IP addresses affect who is excluded.
- Same-origin WebSocket validation, payload limits, and per-socket message/skip limits.
- Full-screen video with a floating control bar and icon-only camera/microphone toggles.
- First-visit 18+ confirmation, remembered in a `cruze_adult` cookie for 365 days (SameSite=Lax; Secure on HTTPS). No camera access until Start is clicked.

The server stores visitor and match metadata in a local SQLite database for the password-protected admin page. It never receives or records audio/video and does not persist SDP or ICE payloads. Public STUN discovery currently uses `stun.l.google.com:19302`; change the STUN-only configuration in `static/app.js` if needed. STUN receives network discovery requests, not video. Partners can learn each other’s public connection IP addresses and may record locally.

## Testing

```sh
uv run pytest -q
uv run playwright install chromium
# With the server running in another terminal:
uv run python tests/browser_smoke.py
uv run python tests/block_browser.py
uv run python tests/playback_regression.py
uv run python tests/camera_browser.py
PYTHONPATH=. uv run python tests/admin_browser.py
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

## Admin activity log

`/admin` provides password-protected visitor, match, and event logs with IP/ID search and pagination. Visits include time, IP address, browser, and a browser visitor ID. Match records include both session IDs and IP addresses, match/start/end times, connected duration, and the participant and action that ended the match.

Connected duration begins when both browsers report a WebRTC connection and excludes reported interruptions. These are client-reported times, not server observation of the P2P media. Logging begins when this feature is enabled; earlier activity cannot be reconstructed. Browser identifiers can reset when cookies are cleared.

Set `CRUZE_ADMIN_PASSWORD_HASH` to a salted scrypt hash generated by `admin.password_hash`; do not put the actual password in source control. Without a configured hash, login is disabled. Sessions expire after eight hours, use an HttpOnly cookie, and are invalidated on logout or application restart. Failed login attempts are rate-limited.

Running `server.py` stores metadata in `data/audit.sqlite3` by default; `CRUZE_DB` overrides the database path. Keep the database outside the public static directory and restrict access. There is no automatic log deletion. Graceful restarts mark active calls as server shutdowns; recovery from an unclean restart closes unfinished records at the last known heartbeat or connection time, so those durations are approximate.

Country codes use a local [DB-IP Country Lite](https://db-ip.com/db/download/ip-to-country-lite) database (CC BY 4.0). Run `uv run python deploy/update-country.py` to download the current monthly release, then restart the application. Deployments also refresh the database. `CRUZE_COUNTRY_DB` overrides the default `data/country.mmdb` path. Lookups cover existing records using the currently installed database; they are approximate IP locations, not verified visitor locations. Missing databases, private addresses, and unknown results display a dash. Visitor IPs are not sent to a geolocation API.

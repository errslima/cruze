"""Cruze: ephemeral matchmaking and signaling. Media stays in browsers."""
import asyncio
import json
import ipaddress
import os
import time
import uuid
from collections import deque
from pathlib import Path
from urllib.parse import unquote

from aiohttp import WSMsgType, web
from audit import Audit
from diagnostics import install_diagnostics
from admin import install_admin

BLOCK_COOKIE = "cruze_blocks"
YEAR_MS = 365 * 24 * 60 * 60 * 1000


def normalize_ip(value):
    address = ipaddress.ip_address(value)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return str(address)


def client_ip(request):
    remote = normalize_ip(request.remote)
    if os.getenv("CRUZE_TRUST_PROXY") == "1" and ipaddress.ip_address(remote).is_loopback:
        try:
            return normalize_ip(request.headers["X-Cruze-Client-IP"])
        except (KeyError, ValueError):
            raise web.HTTPBadRequest(text="Missing or invalid proxy client address")
    return remote


def cookie_blocks(value):
    try:
        if len(value) > 3500:
            return set()
        entries = json.loads(unquote(value))
        now = time.time() * 1000
        if not isinstance(entries, dict):
            return set()
        return {normalize_ip(ip) for ip, expiry in entries.items()
                if isinstance(expiry, (int, float)) and now < expiry <= now + YEAR_MS + 60000}
    except (ValueError, TypeError):
        return set()


STATIC = Path(__file__).parent / "static"


class Lobby:
    def __init__(self, audit=None):
        self.audit = audit
        self.closing = False
        self.clients = {}
        self.addresses = {}
        self.blocked = {}
        self.queue = []
        self.matches = {}
        self.skipped = {}
        self.skip_sequence = 0

    async def send(self, user, kind, **data):
        socket = self.clients.get(user)
        if socket is not None and not socket.closed:
            await socket.send_json({"type": kind, **data})

    async def pair(self):
        if self.closing:
            return
        while True:
            # Never-skipped pairs rank first, then oldest skips. Iteration
            # order breaks ties in favor of users who have waited longest.
            pair = min(((a, b) for i, a in enumerate(self.queue)
                        for b in self.queue[i + 1:]
                        if self.addresses.get(b) not in self.blocked.get(a, set())
                        and self.addresses.get(a) not in self.blocked.get(b, set())),
                       key=lambda pair: self.skipped.get(frozenset(pair), 0),
                       default=None)
            if pair is None:
                return
            a, b = pair
            self.queue.remove(a)
            self.queue.remove(b)
            match = uuid.uuid4().hex
            if self.audit:
                self.audit.match(match, a, b)
            self.matches[a] = (b, match)
            self.matches[b] = (a, match)
            await self.send(a, "matched", matchId=match, initiator=True, peerIp=self.addresses.get(b))
            await self.send(b, "matched", matchId=match, initiator=False, peerIp=self.addresses.get(a))

    async def join(self, user):
        if user not in self.queue and user not in self.matches:
            self.queue.append(user)
            await self.send(user, "waiting")
        await self.pair()

    async def leave(self, user, reason="disconnect"):
        if user in self.queue:
            self.queue.remove(user)
        old = self.matches.pop(user, None)
        if old:
            peer, match = old
            if self.audit:
                self.audit.end_match(match, None if reason == "server_shutdown" else user, reason)
            self.matches.pop(peer, None)
            await self.send(peer, "peer-left", matchId=match)
            self.queue.append(peer)
            await self.send(peer, "waiting")
            # Let the caller enqueue the skipper before choosing any pairs.

    async def message(self, user, data):
        kind = data.get("type")
        if kind == "join":
            if self.audit and user not in self.queue and user not in self.matches:
                self.audit.event(user, None, 'join_queue')
            await self.join(user)
        elif kind in ("next", "stop"):
            # Ignore delayed controls from an earlier pairing.
            current = self.matches.get(user)
            if data.get("matchId") and (not current or current[1] != data["matchId"]):
                return
            if kind == "next" and current:
                self.skip_sequence += 1
                self.skipped[frozenset((user, current[0]))] = self.skip_sequence
            reason = 'skip' if kind == 'next' else data.get('reason', 'stop')
            if reason not in ('skip', 'stop', 'page_closed', 'connection_failed'):
                reason = 'stop'
            if self.audit and not current:
                self.audit.event(user, None, reason)
            await self.leave(user, reason)
            if kind == "next":
                await self.join(user)
            else:
                await self.pair()
        elif kind == "block":
            # This is the caller's own exclusion list, never an identity claim.
            ip = normalize_ip(data.get("ip"))
            self.blocked.setdefault(user, set()).add(ip)
            current = self.matches.get(user)
            # A late confirmation must not skip an unrelated new partner.
            if current and self.addresses.get(current[0]) == ip:
                await self.leave(user, 'block')
                await self.join(user)
            else:
                await self.pair()
        elif kind == "connection":
            current = self.matches.get(user)
            state = data.get('state')
            if current and data.get('matchId') == current[1] and state in ('connected', 'disconnected', 'failed'):
                if self.audit:
                    self.audit.connection(current[1], user, state)
        elif kind == "signal":
            current = self.matches.get(user)
            if not current or data.get("matchId") != current[1]:
                return
            signal = data.get("signal")
            if not isinstance(signal, dict):
                raise ValueError("Invalid signal")
            if signal.get("type") in ("offer", "answer"):
                if not isinstance(signal.get("sdp"), str):
                    raise ValueError("Invalid description")
                signal = {"type": signal["type"], "sdp": signal["sdp"]}
            elif signal.get("type") == "candidate":
                candidate = signal.get("candidate")
                if not isinstance(candidate, dict) or not isinstance(candidate.get("candidate"), str):
                    raise ValueError("Invalid candidate")
            else:
                raise ValueError("Unknown signal")
            await self.send(current[0], "signal", matchId=current[1], signal=signal)
        else:
            raise ValueError("Unknown message")


def create_app(db_path=None):
    app = web.Application(client_max_size=65536)
    audit = Audit(db_path or os.getenv("CRUZE_DB", ":memory:"))
    lobby = Lobby(audit)
    install_admin(app, audit, client_ip)
    install_diagnostics(app, audit)
    lock = asyncio.Lock()

    async def websocket(request):
        origin = request.headers.get("Origin")
        allowed = os.getenv("CRUZE_ORIGIN", f"{request.scheme}://{request.host}")
        if origin != allowed:
            raise web.HTTPForbidden(text="Origin rejected")
        address = client_ip(request)
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=65536)
        await ws.prepare(request)
        user = uuid.uuid4().hex
        lobby.clients[user] = ws
        lobby.addresses[user] = address
        lobby.blocked[user] = cookie_blocks(request.cookies.get(BLOCK_COOKIE, ""))
        audit.session(user, request.query.get('visit', ''), request.cookies.get('cruze_visitor', ''), address,
                      request.headers.get('User-Agent', ''))
        events, controls = deque(), deque()
        end_reason = 'disconnect'
        try:
            async for message in ws:
                if message.type != WSMsgType.TEXT:
                    continue
                now = time.monotonic()
                while events and events[0] < now - 10:
                    events.popleft()
                events.append(now)
                if len(events) > 150:
                    end_reason = "rate_limit"
                    await ws.close(code=1008, message=b"Too many messages")
                    break
                try:
                    data = json.loads(message.data)
                    if not isinstance(data, dict):
                        raise ValueError("Expected an object")
                    if data.get("type") in ("join", "next", "block"):
                        while controls and controls[0] < now - 10:
                            controls.popleft()
                        controls.append(now)
                        if len(controls) > 10:
                            end_reason = "rate_limit"
                            await ws.close(code=1008, message=b"Too many skips")
                            break
                    async with lock:
                        await lobby.message(user, data)
                except (ValueError, TypeError):
                    end_reason = "invalid_message"
                    await ws.close(code=1008, message=b"Invalid message")
                    break
        finally:
            async with lock:
                reason = 'server_shutdown' if lobby.closing else end_reason
                await lobby.leave(user, reason)
                audit.end_session(user, reason)
                lobby.clients.pop(user, None)
                lobby.addresses.pop(user, None)
                lobby.blocked.pop(user, None)
                for pair in list(lobby.skipped):
                    if user in pair:
                        del lobby.skipped[pair]
                await lobby.pair()
        return ws

    map_cache = {'expires': 0, 'countries': {}}

    async def visitor_map(request):
        now = time.monotonic()
        if now >= map_cache['expires']:
            map_cache['countries'] = audit.country_totals()
            map_cache['expires'] = now + 60
        return web.json_response({'countries': map_cache['countries']}, headers={
            'Cache-Control': 'public, max-age=60', 'X-Content-Type-Options': 'nosniff'})

    async def asset(request):
        name = request.match_info.get("name", "index.html")
        if name not in ("index.html", "app.js", "style.css", "world.js", "world.json"):
            raise web.HTTPNotFound()
        headers = {
            "Cache-Control": "no-cache",
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; media-src 'self' blob:; object-src 'none'; frame-ancestors 'none'",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Permissions-Policy": "camera=(self), microphone=(self)",
        }
        if name == 'index.html':
            visitor = request.cookies.get('cruze_visitor', '')
            try:
                visitor = uuid.UUID(visitor).hex
            except ValueError:
                visitor = uuid.uuid4().hex
            visit = uuid.uuid4().hex
            # Health probes use HEAD and do not count as visitors.
            if request.method != 'HEAD':
                audit.visit(visit, visitor, client_ip(request), request.headers.get('User-Agent', ''),
                            request.headers.get('Referer', '').split('?')[0])
            content = (STATIC / name).read_text().replace('</head>', f'<meta name="cruze-visit" content="{visit}"></head>')
            headers['Cache-Control'] = 'no-store'
            response = web.Response(text=content, content_type='text/html', headers=headers)
            response.set_cookie('cruze_visitor', visitor, max_age=31536000, httponly=True,
                                secure=os.getenv('CRUZE_ORIGIN', request.scheme).startswith('https'),
                                samesite='Lax')
            return response
        return web.FileResponse(STATIC / name, headers=headers)

    async def heartbeat():
        while True:
            audit.heartbeat()
            await asyncio.sleep(10)

    async def startup(app):
        app[heartbeat_key] = asyncio.create_task(heartbeat())

    async def shutdown(app):
        lobby.closing = True
        for user in list(lobby.matches):
            await lobby.leave(user, 'server_shutdown')
        await asyncio.gather(*(ws.close(code=1001) for ws in list(lobby.clients.values())))

    async def cleanup(app):
        app[heartbeat_key].cancel()
        await asyncio.gather(app[heartbeat_key], return_exceptions=True)
        audit.heartbeat()
        audit.close()

    heartbeat_key = web.AppKey('heartbeat', asyncio.Task)
    app.on_startup.append(startup)
    app.on_cleanup.append(cleanup)
    app.router.add_get("/api/visitor-map", visitor_map)
    app.router.add_get("/ws", websocket)
    app.router.add_get("/", asset)
    app.router.add_get("/{name}", asset)
    app.on_shutdown.append(shutdown)
    return app


if __name__ == "__main__":
    web.run_app(create_app(os.getenv("CRUZE_DB", "data/audit.sqlite3")), host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))

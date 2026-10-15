"""Cruze: ephemeral matchmaking and signaling. Media stays in browsers."""
import asyncio
import json
import os
import time
import uuid
from collections import deque
from pathlib import Path

from aiohttp import WSMsgType, web

STATIC = Path(__file__).parent / "static"


class Lobby:
    def __init__(self):
        self.clients = {}
        self.queue = []
        self.matches = {}
        self.skipped = {}
        self.skip_sequence = 0

    async def send(self, user, kind, **data):
        socket = self.clients.get(user)
        if socket is not None and not socket.closed:
            await socket.send_json({"type": kind, **data})

    async def pair(self):
        while True:
            # Never-skipped pairs rank first, then oldest skips. Iteration
            # order breaks ties in favor of users who have waited longest.
            pair = min(((a, b) for i, a in enumerate(self.queue)
                        for b in self.queue[i + 1:]),
                       key=lambda pair: self.skipped.get(frozenset(pair), 0),
                       default=None)
            if pair is None:
                return
            a, b = pair
            self.queue.remove(a)
            self.queue.remove(b)
            match = uuid.uuid4().hex
            self.matches[a] = (b, match)
            self.matches[b] = (a, match)
            await self.send(a, "matched", matchId=match, initiator=True)
            await self.send(b, "matched", matchId=match, initiator=False)

    async def join(self, user):
        if user not in self.queue and user not in self.matches:
            self.queue.append(user)
            await self.send(user, "waiting")
        await self.pair()

    async def leave(self, user):
        if user in self.queue:
            self.queue.remove(user)
        old = self.matches.pop(user, None)
        if old:
            peer, match = old
            self.matches.pop(peer, None)
            await self.send(peer, "peer-left", matchId=match)
            self.queue.append(peer)
            await self.send(peer, "waiting")
            # Let the caller enqueue the skipper before choosing any pairs.

    async def message(self, user, data):
        kind = data.get("type")
        if kind == "join":
            await self.join(user)
        elif kind in ("next", "stop"):
            # Ignore delayed controls from an earlier pairing.
            current = self.matches.get(user)
            if data.get("matchId") and (not current or current[1] != data["matchId"]):
                return
            if kind == "next" and current:
                self.skip_sequence += 1
                self.skipped[frozenset((user, current[0]))] = self.skip_sequence
            await self.leave(user)
            if kind == "next":
                await self.join(user)
            else:
                await self.pair()
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


def create_app():
    app = web.Application(client_max_size=65536)
    lobby = Lobby()
    lock = asyncio.Lock()

    async def websocket(request):
        origin = request.headers.get("Origin")
        allowed = os.getenv("CRUZE_ORIGIN", f"{request.scheme}://{request.host}")
        if origin != allowed:
            raise web.HTTPForbidden(text="Origin rejected")
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=65536)
        await ws.prepare(request)
        user = uuid.uuid4().hex
        lobby.clients[user] = ws
        events, controls = deque(), deque()
        try:
            async for message in ws:
                if message.type != WSMsgType.TEXT:
                    continue
                now = time.monotonic()
                while events and events[0] < now - 10:
                    events.popleft()
                events.append(now)
                if len(events) > 150:
                    await ws.close(code=1008, message=b"Too many messages")
                    break
                try:
                    data = json.loads(message.data)
                    if not isinstance(data, dict):
                        raise ValueError("Expected an object")
                    if data.get("type") in ("join", "next"):
                        while controls and controls[0] < now - 10:
                            controls.popleft()
                        controls.append(now)
                        if len(controls) > 10:
                            await ws.close(code=1008, message=b"Too many skips")
                            break
                    async with lock:
                        await lobby.message(user, data)
                except (ValueError, TypeError):
                    await ws.close(code=1008, message=b"Invalid message")
                    break
        finally:
            async with lock:
                await lobby.leave(user)
                lobby.clients.pop(user, None)
                for pair in list(lobby.skipped):
                    if user in pair:
                        del lobby.skipped[pair]
                await lobby.pair()
        return ws

    async def asset(request):
        name = request.match_info.get("name", "index.html")
        if name not in ("index.html", "app.js", "style.css"):
            raise web.HTTPNotFound()
        return web.FileResponse(STATIC / name, headers={
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; media-src 'self' blob:; object-src 'none'; frame-ancestors 'none'",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Permissions-Policy": "camera=(self), microphone=(self)",
        })

    async def shutdown(app):
        await asyncio.gather(*(ws.close(code=1001) for ws in list(lobby.clients.values())))

    app.router.add_get("/ws", websocket)
    app.router.add_get("/", asset)
    app.router.add_get("/{name}", asset)
    app.on_shutdown.append(shutdown)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))

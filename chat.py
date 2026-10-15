"""Text lobby shared by everyone on the page. Text only; names are assigned, not chosen."""
import asyncio
import hashlib
import os
import re
import time
import uuid
from collections import deque

from aiohttp import WSMsgType, web

HISTORY = 50
MAX_TEXT = 300
SOCKETS_PER_IP = 8
ADJECTIVES = ('Amber', 'Brave', 'Calm', 'Clever', 'Cosmic', 'Curious', 'Dapper', 'Eager', 'Fuzzy', 'Gentle',
              'Golden', 'Happy', 'Jolly', 'Lucky', 'Lunar', 'Mellow', 'Misty', 'Nimble', 'Quiet', 'Rapid',
              'Rusty', 'Silver', 'Sleepy', 'Smooth', 'Sunny', 'Swift', 'Tidy', 'Velvet', 'Witty', 'Zesty',
              'Bold', 'Breezy')
ANIMALS = ('Badger', 'Beaver', 'Bison', 'Crane', 'Dolphin', 'Falcon', 'Ferret', 'Finch', 'Fox', 'Gecko',
           'Heron', 'Ibis', 'Koala', 'Lemur', 'Lynx', 'Marten', 'Moose', 'Newt', 'Otter', 'Owl',
           'Panda', 'Puffin', 'Quokka', 'Raven', 'Seal', 'Sloth', 'Swan', 'Tapir', 'Tiger', 'Walrus',
           'Wombat', 'Yak')
# Control characters and bidirectional overrides, which can disguise text.
UNSAFE = re.compile('[\x00-\x1f\x7f​-‏‪-‮⁦-⁩]')


def lobby_name(visitor):
    digest = hashlib.sha256(visitor.encode()).digest()
    return f'{ADJECTIVES[digest[0] % len(ADJECTIVES)]} {ANIMALS[digest[1] % len(ANIMALS)]}'


def clean_text(value):
    if not isinstance(value, str):
        raise ValueError('Expected text')
    text = ' '.join(UNSAFE.sub(' ', value).split())
    if len(text) > MAX_TEXT:
        raise ValueError('Message too long')
    return text


class Chat:
    def __init__(self, audit):
        self.audit = audit
        self.members = {}
        self.sent = {}

    def online(self):
        return len({member['visitor'] for member in self.members.values()})

    @staticmethod
    def public(row, member):
        # Never expose IPs or visitor IDs, only whether a message is the viewer's own.
        return {'id': row['id'], 'at': row['at'], 'name': row['name'], 'country': row['country'],
                'text': row['text'], 'mine': row['visitor'] == member['visitor']}

    async def broadcast(self, build):
        sends = []
        for ws, member in list(self.members.items()):
            data = build(member)
            if data is not None and not ws.closed:
                sends.append(ws.send_json(data))
        await asyncio.gather(*sends, return_exceptions=True)

    async def announce_online(self):
        count = self.online()
        await self.broadcast(lambda member: {'type': 'online', 'count': count})

    def allow(self, ip):
        now = time.monotonic()
        # Kept across reconnects, so a new socket does not reset the limit.
        for key in [key for key, times in self.sent.items() if times[-1] < now - 10]:
            del self.sent[key]
        recent = self.sent.setdefault(ip, deque())
        while recent and recent[0] < now - 10:
            recent.popleft()
        if len(recent) >= 5:
            return False
        recent.append(now)
        return True

    async def say(self, member, text):
        row = self.audit.chat(member['visitor'], member['ip'], member['name'], member['country'], text)
        await self.broadcast(lambda other: None if row['ip'] in other['blocked']
                             else {'type': 'message', **self.public(row, other)})

    async def remove(self, ident):
        if self.audit.hide_chat(ident):
            await self.broadcast(lambda member: {'type': 'removed', 'id': ident})
            return True
        return False


def install_chat(app, audit, get_ip, read_blocks, normalize_ip):
    chat = Chat(audit)

    async def lobby(request):
        origin = request.headers.get('Origin')
        if origin != os.getenv('CRUZE_ORIGIN', f'{request.scheme}://{request.host}'):
            raise web.HTTPForbidden(text='Origin rejected')
        if request.cookies.get('cruze_adult') != '1':
            raise web.HTTPForbidden(text='Confirm you are 18 or older first')
        ip = get_ip(request)
        if sum(member['ip'] == ip for member in chat.members.values()) >= SOCKETS_PER_IP:
            raise web.HTTPTooManyRequests(text='Too many open lobby connections')
        try:
            visitor = uuid.UUID(request.cookies.get('cruze_visitor', '')).hex
        except ValueError:
            visitor = 'anonymous-' + uuid.uuid4().hex
        ws = web.WebSocketResponse(heartbeat=30, max_msg_size=4096)
        await ws.prepare(request)
        member = {'visitor': visitor, 'ip': ip, 'name': lobby_name(visitor),
                  'country': audit.countries.lookup(ip), 'blocked': read_blocks(request.cookies.get('cruze_blocks', ''))}
        chat.members[ws] = member
        history = [chat.public(row, member) for row in audit.chat_history(HISTORY) if row['ip'] not in member['blocked']]
        await ws.send_json({'type': 'hello', 'name': member['name'], 'country': member['country'],
                            'online': chat.online(), 'history': history})
        await chat.announce_online()
        frames = deque()
        try:
            async for message in ws:
                if message.type != WSMsgType.TEXT:
                    continue
                now = time.monotonic()
                while frames and frames[0] < now - 10:
                    frames.popleft()
                frames.append(now)
                if len(frames) > 30:
                    await ws.close(code=1008, message=b'Too many messages')
                    break
                try:
                    data = message.json()
                    if not isinstance(data, dict):
                        raise ValueError('Expected an object')
                    if data.get('type') == 'say':
                        text = clean_text(data.get('text'))
                        if not text:
                            continue
                        if not chat.allow(ip):
                            await ws.send_json({'type': 'error', 'message': 'You’re sending messages too quickly. Wait a few seconds.'})
                            continue
                        await chat.say(member, text)
                    elif data.get('type') == 'block':
                        # The caller's own filter, matching the video block cookie.
                        member['blocked'].add(normalize_ip(data.get('ip')))
                    else:
                        raise ValueError('Unknown message')
                except (ValueError, TypeError):
                    await ws.close(code=1008, message=b'Invalid message')
                    break
        finally:
            chat.members.pop(ws, None)
            await chat.announce_online()
        return ws

    async def shutdown(app):
        await asyncio.gather(*(ws.close(code=1001) for ws in list(chat.members)), return_exceptions=True)

    app.router.add_get('/lobby', lobby)
    app.on_shutdown.append(shutdown)
    return chat

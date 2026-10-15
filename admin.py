"""Password authentication and private audit log routes."""
import asyncio
import hashlib
import hmac
import os
import secrets
import time
from collections import deque
from pathlib import Path

from aiohttp import web

STATIC = Path(__file__).parent / 'static'
HEADERS = {
    'Cache-Control': 'no-store',
    'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
    'X-Robots-Tag': 'noindex, nofollow',
}


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, maxmem=67108864).hex()
    return salt + ':' + digest


def check_password(password, encoded):
    try:
        salt, _ = encoded.split(':', 1)
        return hmac.compare_digest(password_hash(password, salt), encoded)
    except (ValueError, TypeError):
        return False


def install_admin(app, audit, get_ip):
    sessions = {}
    failures = {}
    attempts = deque()
    configured = os.getenv('CRUZE_ADMIN_PASSWORD_HASH', '')

    def allowed_origin(request):
        return os.getenv('CRUZE_ORIGIN', f'{request.scheme}://{request.host}')

    def auth(request):
        token = request.cookies.get('cruze_admin', '')
        now = time.time()
        for key, expiry in list(sessions.items()):
            if expiry <= now:
                sessions.pop(key, None)
        return sessions.get(hashlib.sha256(token.encode()).hexdigest(), 0) > now

    def require(request):
        if not auth(request):
            raise web.HTTPUnauthorized(headers=HEADERS)

    def same_origin(request):
        if request.headers.get('Origin') != allowed_origin(request):
            raise web.HTTPForbidden(headers=HEADERS)

    async def page(request):
        name = 'admin.html' if auth(request) else 'admin-login.html'
        return web.FileResponse(STATIC / name, headers=HEADERS)

    async def asset(request):
        name = request.match_info['name']
        if name not in ('admin.js', 'admin.css', 'admin-login.js'):
            raise web.HTTPNotFound(headers=HEADERS)
        return web.FileResponse(STATIC / name, headers=HEADERS)

    async def login(request):
        same_origin(request)
        if not configured:
            return web.json_response({'error': 'Admin access has not been configured.'}, status=503, headers=HEADERS)
        ip, now = get_ip(request), time.time()
        for key in list(failures):
            if failures[key][-1] < now - 900:
                del failures[key]
        while attempts and attempts[0] < now - 60:
            attempts.popleft()
        recent = failures.setdefault(ip, deque())
        while recent and recent[0] < now - 900:
            recent.popleft()
        if len(recent) >= 5 or len(attempts) >= 100:
            return web.json_response({'error': 'Too many login attempts. Try again later.'}, status=429, headers=HEADERS)
        # Count attempts before awaiting verification to prevent parallel bypass.
        recent.append(now)
        attempts.append(now)
        try:
            data = await request.json()
            password = data.get('password')
            valid = isinstance(password, str) and 0 < len(password) <= 1024
        except (ValueError, AttributeError):
            valid, password = False, ''
        if not valid or not await asyncio.to_thread(check_password, password, configured):
            return web.json_response({'error': 'Incorrect password.'}, status=401, headers=HEADERS)
        failures.pop(ip, None)
        token = secrets.token_urlsafe(32)
        sessions[hashlib.sha256(token.encode()).hexdigest()] = now + 8 * 3600
        response = web.json_response({'ok': True}, headers=HEADERS)
        response.set_cookie('cruze_admin', token, max_age=8 * 3600, httponly=True,
                            secure=allowed_origin(request).startswith('https://'), samesite='Strict', path='/admin')
        return response

    async def logout(request):
        same_origin(request)
        token = request.cookies.get('cruze_admin', '')
        sessions.pop(hashlib.sha256(token.encode()).hexdigest(), None)
        response = web.json_response({'ok': True}, headers=HEADERS)
        response.del_cookie('cruze_admin', path='/admin')
        return response

    async def logs(request):
        require(request)
        try:
            page_number = max(0, min(int(request.query.get('page', '0')), 10000000))
            result = audit.logs(request.query.get('kind', 'visits'), page_number, request.query.get('q', ''))
        except ValueError:
            raise web.HTTPBadRequest(headers=HEADERS)
        result['summary'] = audit.summary()
        return web.json_response(result, headers=HEADERS)

    app.router.add_get('/admin', page)
    app.router.add_get('/admin/', page)
    app.router.add_get('/admin/assets/{name}', asset)
    app.router.add_post('/admin/login', login)
    app.router.add_post('/admin/logout', logout)
    app.router.add_get('/admin/api/logs', logs)

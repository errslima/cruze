import asyncio
import re
import pytest
from aiohttp import CookieJar
from aiohttp.test_utils import TestClient, TestServer
from admin import password_hash
from audit import Audit
from server import create_app


@pytest.mark.asyncio
async def test_admin_login_protection_visits_and_logout(monkeypatch, tmp_path):
    monkeypatch.setenv('CRUZE_ADMIN_PASSWORD_HASH', password_hash('test-only-password'))
    async with TestClient(TestServer(create_app(str(tmp_path / 'audit.sqlite3'))), cookie_jar=CookieJar(unsafe=True)) as client:
        origin = str(client.make_url('/')).rstrip('/')
        assert (await client.get('/admin/api/logs')).status == 401
        assert 'password' in await (await client.get('/admin')).text()
        assert (await client.get('/admin.html')).status == 404
        assert (await client.get('/audit.sqlite3')).status == 404
        response = await client.get('/', headers={'User-Agent': '<script>alert(1)</script>'})
        assert 'no-store' in response.headers['Cache-Control']
        visit = re.search('name="cruze-visit" content="([a-f0-9]+)"', await response.text()).group(1)
        assert (await client.head('/')).status == 200
        assert (await client.post('/admin/login', json={'password': 'test-only-password'})).status == 403
        assert (await client.post('/admin/login', headers={'Origin': origin}, json={'password': 'wrong'})).status == 401
        response = await client.post('/admin/login', headers={'Origin': origin}, json={'password': 'test-only-password'})
        assert response.status == 200
        cookie = response.cookies['cruze_admin']
        assert cookie['httponly'] and cookie['samesite'] == 'Strict'
        data = await (await client.get('/admin/api/logs')).json()
        assert data['total'] == 1  # HEAD probe excluded.
        assert data['rows'][0]['id'] == visit
        assert data['rows'][0]['agent'] == '<script>alert(1)</script>'
        assert (await client.get('/admin/api/logs?kind=events')).status == 200
        assert (await client.get('/admin/api/logs?kind=matches')).status == 200
        assert 'Activity log' in await (await client.get('/admin')).text()
        assert (await client.post('/admin/logout', headers={'Origin': origin})).status == 200
        assert (await client.get('/admin/api/logs')).status == 401


@pytest.mark.asyncio
async def test_admin_login_rate_limit(monkeypatch):
    monkeypatch.setenv('CRUZE_ADMIN_PASSWORD_HASH', password_hash('test-password'))
    async with TestClient(TestServer(create_app())) as client:
        origin = str(client.make_url('/')).rstrip('/')
        for _ in range(5):
            assert (await client.post('/admin/login', headers={'Origin': origin}, json={'password': 'wrong'})).status == 401
        assert (await client.post('/admin/login', headers={'Origin': origin}, json={'password': 'test-password'})).status == 429


def test_match_durations_exclude_setup_and_interruptions(monkeypatch, tmp_path):
    clock = [100.0]
    monkeypatch.setattr('audit.time.time', lambda: clock[0])
    path = str(tmp_path / 'audit.sqlite3')
    audit = Audit(path)
    for user, ip in [('a', '192.0.2.1'), ('b', '192.0.2.2')]:
        audit.session(user, '', user, ip, 'Test')
    audit.match('match', 'a', 'b')
    clock[0] = 102
    audit.connection('match', 'a', 'connected')
    clock[0] = 104
    audit.connection('match', 'b', 'connected')
    clock[0] = 110
    audit.connection('match', 'a', 'disconnected')
    clock[0] = 114
    audit.connection('match', 'a', 'connected')
    clock[0] = 119
    audit.end_match('match', 'b', 'skip')
    audit.end_match('match', 'a', 'disconnect')  # End recorded only once.
    row = audit.logs('matches', 0, '')['rows'][0]
    assert row['connected_seconds'] == 11
    assert row['connected'] == 104
    assert row['ended_by'] == 'b' and row['reason'] == 'skip'
    assert row['a_ip'] == '192.0.2.1'
    audit.close()
    restored = Audit(path)
    assert restored.logs('matches', 0, '')['rows'][0]['connected_seconds'] == 11
    restored.close()


def test_crash_recovery_and_pagination(monkeypatch, tmp_path):
    clock = [100.0]
    monkeypatch.setattr('audit.time.time', lambda: clock[0])
    path = str(tmp_path / 'audit.sqlite3')
    audit = Audit(path)
    audit.session('a', '', 'v', '192.0.2.1', 'test')
    audit.session('b', '', 'w', '192.0.2.2', 'test')
    audit.match('open', 'a', 'b')
    audit.connection('open', 'a', 'connected')
    audit.connection('open', 'b', 'connected')
    clock[0] = 110
    audit.heartbeat()
    for n in range(105):
        audit.visit(str(n), 'v', '192.0.2.1', 'test', '')
    audit.close()
    clock[0] = 200
    restored = Audit(path)
    row = restored.logs('matches', 0, '')['rows'][0]
    assert row['ended'] == 110 and row['reason'] == 'server_restart'
    assert row['connected_seconds'] == 10
    assert len(restored.logs('visits', 1, '')['rows']) == 5
    assert restored.logs('visits', 0, '192.0.2.99')['total'] == 0
    assert restored.summary()['sessions'] == 0
    restored.close()


@pytest.mark.asyncio
async def test_logged_match_end_and_visit_link(monkeypatch, tmp_path):
    monkeypatch.setenv('CRUZE_ADMIN_PASSWORD_HASH', password_hash('test-password'))
    async with TestClient(TestServer(create_app(str(tmp_path / 'audit.sqlite3'))), cookie_jar=CookieJar(unsafe=True)) as client:
        origin = str(client.make_url('/')).rstrip('/')
        page = await client.get('/')
        visit = re.search('name="cruze-visit" content="([a-f0-9]+)"', await page.text()).group(1)
        a, b = [await client.ws_connect('/ws?visit=' + visit, origin=origin) for _ in range(2)]
        for ws in (a, b):
            await ws.send_json({'type': 'join'})
            assert (await ws.receive_json())['type'] == 'waiting'
        matches = [await ws.receive_json() for ws in (a, b)]
        ident = matches[0]['matchId']
        for ws in (a, b):
            await ws.send_json({'type': 'connection', 'matchId': ident, 'state': 'connected'})
        await asyncio.sleep(.02)
        await a.send_json({'type': 'next', 'matchId': ident})
        for _ in range(2):
            await a.receive_json()
        await a.close()
        await b.close()
        await client.post('/admin/login', headers={'Origin': origin}, json={'password': 'test-password'})
        rows = (await (await client.get('/admin/api/logs?kind=matches')).json())['rows']
        row = next(row for row in rows if row['id'] == ident)
        assert row['reason'] == 'skip' and row['connected_seconds'] > 0
        visits = await (await client.get('/admin/api/logs')).json()
        assert visits['rows'][0]['sessions'] == 2

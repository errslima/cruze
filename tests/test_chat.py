import asyncio
import json
import time
import uuid
from urllib.parse import quote

import pytest
from aiohttp import CookieJar, WSMsgType, WSServerHandshakeError
from aiohttp.test_utils import TestClient, TestServer
from admin import password_hash
from chat import clean_text, lobby_name
from server import create_app


@pytest.fixture
async def app_client(tmp_path):
    async with TestClient(TestServer(create_app(str(tmp_path / 'audit.sqlite3')))) as client:
        yield client


def origin(client):
    return str(client.make_url('/')).rstrip('/')


async def join(client, visitor=None, blocks=None, adult=True):
    cookies = [f'cruze_visitor={visitor or uuid.uuid4().hex}']
    if adult:
        cookies.append('cruze_adult=1')
    if blocks:
        cookies.append('cruze_blocks=' + quote(json.dumps(blocks)))
    return await client.ws_connect('/lobby', headers={'Origin': origin(client), 'Cookie': '; '.join(cookies)})


async def receive(ws, kind):
    while True:
        message = await asyncio.wait_for(ws.receive_json(), 2)
        if message['type'] == kind:
            return message
        assert message['type'] == 'online', message


async def until_online(ws, count):
    while (await receive(ws, 'online'))['count'] != count:
        pass


async def close_code(ws):
    while True:
        message = await asyncio.wait_for(ws.receive(), 2)
        if message.type == WSMsgType.CLOSE:
            return message.data


def test_names_and_text_cleaning():
    visitor = uuid.uuid4().hex
    assert lobby_name(visitor) == lobby_name(visitor)
    assert len(lobby_name(visitor).split()) == 2
    assert clean_text('  hi\n\tthere ‮evil ') == 'hi there evil'
    assert clean_text('   ') == ''
    with pytest.raises(ValueError):
        clean_text('x' * 301)
    with pytest.raises(ValueError):
        clean_text(42)


async def test_messages_reach_everyone_and_history_survives(app_client):
    a_visitor = uuid.uuid4().hex
    a = await join(app_client, a_visitor)
    hello = await receive(a, 'hello')
    assert hello['history'] == [] and hello['online'] == 1
    assert hello['name'] == lobby_name(a_visitor)
    b = await join(app_client)
    assert (await receive(b, 'hello'))['online'] == 2
    await until_online(a, 2)
    await a.send_json({'type': 'say', 'text': '  hello\nworld  '})
    mine, theirs = await receive(a, 'message'), await receive(b, 'message')
    assert mine['text'] == theirs['text'] == 'hello world'
    assert mine['mine'] and not theirs['mine']
    assert mine['name'] == lobby_name(a_visitor)
    assert 'ip' not in theirs and 'visitor' not in theirs
    # Whitespace-only messages are ignored, not stored.
    await a.send_json({'type': 'say', 'text': '   '})
    # A second tab of the same browser counts once and sees its own messages as mine.
    a2 = await join(app_client, a_visitor)
    late = await receive(a2, 'hello')
    assert late['online'] == 2
    assert [m['text'] for m in late['history']] == ['hello world'] and late['history'][0]['mine']
    for ws in (a, b, a2):
        await ws.close()


async def test_origin_age_and_invalid_messages(app_client):
    with pytest.raises(WSServerHandshakeError):
        await app_client.ws_connect('/lobby', headers={'Origin': 'https://evil.example', 'Cookie': 'cruze_adult=1'})
    with pytest.raises(WSServerHandshakeError):
        await join(app_client, adult=False)
    ws = await join(app_client)
    await receive(ws, 'hello')
    await ws.send_json({'type': 'say', 'text': 'x' * 301})
    assert await close_code(ws) == 1008
    ws = await join(app_client)
    await receive(ws, 'hello')
    await ws.send_str('not json')
    assert await close_code(ws) == 1008


async def test_rate_limit_survives_reconnect(app_client):
    ws = await join(app_client)
    await receive(ws, 'hello')
    for index in range(5):
        await ws.send_json({'type': 'say', 'text': f'message {index}'})
        await receive(ws, 'message')
    await ws.send_json({'type': 'say', 'text': 'too many'})
    assert 'quickly' in (await receive(ws, 'error'))['message']
    await ws.close()
    again = await join(app_client)
    await receive(again, 'hello')
    await again.send_json({'type': 'say', 'text': 'still too many'})
    await receive(again, 'error')
    await again.close()


async def test_blocks_hide_messages_from_that_ip(app_client):
    # Test clients connect from 127.0.0.1, so blocking it hides everyone here.
    sender = await join(app_client)
    await receive(sender, 'hello')
    await sender.send_json({'type': 'say', 'text': 'before'})
    await receive(sender, 'message')
    blocker = await join(app_client, blocks={'127.0.0.1': time.time() * 1000 + 86400000})
    assert (await receive(blocker, 'hello'))['history'] == [], 'blocked history hidden'
    live = await join(app_client)
    assert len((await receive(live, 'hello'))['history']) == 1
    await live.send_json({'type': 'block', 'ip': '127.0.0.1'})
    await sender.send_json({'type': 'say', 'text': 'after'})
    await receive(sender, 'message')
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(receive(live, 'message'), .5)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(receive(blocker, 'message'), .5)
    for ws in (sender, blocker, live):
        await ws.close()


async def test_admin_can_list_and_remove_messages(monkeypatch, tmp_path):
    monkeypatch.setenv('CRUZE_ADMIN_PASSWORD_HASH', password_hash('test-only-password'))
    async with TestClient(TestServer(create_app(str(tmp_path / 'audit.sqlite3'))), cookie_jar=CookieJar(unsafe=True)) as client:
        ws = await join(client)
        await receive(ws, 'hello')
        await ws.send_json({'type': 'say', 'text': 'please remove me'})
        sent = await receive(ws, 'message')
        assert (await client.post('/admin/api/chat/hide', headers={'Origin': origin(client)}, json={'id': sent['id']})).status == 401
        await client.post('/admin/login', headers={'Origin': origin(client)}, json={'password': 'test-only-password'})
        logs = await (await client.get('/admin/api/logs?kind=chat&q=remove')).json()
        assert logs['total'] == 1 and logs['rows'][0]['ip'] == '127.0.0.1'
        assert (await client.post('/admin/api/chat/hide', json={'id': sent['id']})).status == 403
        assert (await client.post('/admin/api/chat/hide', headers={'Origin': origin(client)}, json={'id': 'x'})).status == 400
        response = await client.post('/admin/api/chat/hide', headers={'Origin': origin(client)}, json={'id': sent['id']})
        assert (await response.json())['removed']
        assert (await receive(ws, 'removed'))['id'] == sent['id']
        fresh = await join(client)
        assert (await receive(fresh, 'hello'))['history'] == []
        for socket in (ws, fresh):
            await socket.close()

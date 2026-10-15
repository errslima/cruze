import asyncio
import pytest
from aiohttp.test_utils import TestClient, TestServer
from server import create_app


@pytest.fixture
async def client():
    async with TestClient(TestServer(create_app())) as client:
        yield client


async def connect(client):
    return await client.ws_connect('/ws', headers={'Origin': str(client.make_url('/')).rstrip('/')})


async def receive(ws, kind):
    message = await asyncio.wait_for(ws.receive_json(), 2)
    assert message['type'] == kind
    return message


@pytest.mark.asyncio
async def test_pair_signal_skip_disconnect(client):
    a, b, c = [await connect(client) for _ in range(3)]
    await a.send_json({'type': 'join'})
    await receive(a, 'waiting')
    await b.send_json({'type': 'join'})
    await receive(b, 'waiting')
    am, bm = await receive(a, 'matched'), await receive(b, 'matched')
    assert am['matchId'] == bm['matchId']
    assert am['initiator'] != bm['initiator']
    await a.send_json({'type': 'signal', 'matchId': am['matchId'], 'signal': {'type': 'offer', 'sdp': 'test'}})
    assert (await receive(b, 'signal'))['signal']['sdp'] == 'test'
    await c.send_json({'type': 'join'})
    await receive(c, 'waiting')
    await a.send_json({'type': 'next', 'matchId': am['matchId']})
    await receive(b, 'peer-left')
    await receive(b, 'waiting')
    new = await receive(b, 'matched')
    await receive(c, 'matched')
    await receive(a, 'waiting')
    assert new['matchId'] != am['matchId']
    # An old match cannot signal a new partner.
    await b.send_json({'type': 'signal', 'matchId': am['matchId'], 'signal': {'type': 'offer', 'sdp': 'stale'}})
    await b.close()
    await receive(c, 'peer-left')
    await receive(c, 'waiting')
    cm = await receive(c, 'matched')
    assert (await receive(a, 'matched'))['matchId'] == cm['matchId']
    await a.close()
    await c.close()


@pytest.mark.asyncio
async def test_skip_does_not_immediately_rematch_same_pair(client):
    a, b = await connect(client), await connect(client)
    for ws in (a, b):
        await ws.send_json({'type': 'join'})
        await receive(ws, 'waiting')
    match = await receive(a, 'matched')
    await receive(b, 'matched')
    await a.send_json({'type': 'next', 'matchId': match['matchId']})
    await receive(b, 'peer-left')
    await receive(b, 'waiting')
    await receive(a, 'waiting')
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(a.receive_json(), .1)
    await a.close()
    await b.close()


@pytest.mark.asyncio
async def test_origin_and_invalid_messages(client):
    response = await client.get('/ws', headers={'Origin': 'https://foreign.example'})
    assert response.status == 403
    ws = await connect(client)
    await ws.send_str('[]')
    await ws.receive()
    assert ws.close_code == 1008


@pytest.mark.asyncio
async def test_static_assets_and_no_traversal(client):
    for path in ('/', '/app.js', '/style.css'):
        response = await client.get(path)
        assert response.status == 200
        assert 'frame-ancestors' in response.headers['Content-Security-Policy']
    assert (await client.get('/server.py')).status == 404

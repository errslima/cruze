import asyncio
import pytest
from aiohttp.test_utils import TestClient, TestServer
from server import Lobby, create_app


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
async def test_skip_rematches_only_available_pair(client):
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
    rematch_a, rematch_b = await receive(a, 'matched'), await receive(b, 'matched')
    assert rematch_a['matchId'] == rematch_b['matchId']
    assert rematch_a['matchId'] != match['matchId']
    # A simultaneous skip from the old match must not tear down the new one.
    await b.send_json({'type': 'next', 'matchId': match['matchId']})
    await a.send_json({'type': 'signal', 'matchId': rematch_a['matchId'],
                       'signal': {'type': 'offer', 'sdp': 'new call'}})
    assert (await receive(b, 'signal'))['signal']['sdp'] == 'new call'
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


@pytest.mark.asyncio
async def test_skipped_pairs_rank_by_recency_and_refresh_on_skip():
    lobby = Lobby()
    # Build real skip history: A/B first, then A/C, then A/D.
    for partner in ('b', 'c', 'd'):
        lobby.queue = []
        lobby.matches = {'a': (partner, partner), partner: ('a', partner)}
        await lobby.message('a', {'type': 'next', 'matchId': partner})
    lobby.matches.clear()
    lobby.queue = ['d', 'c', 'b', 'a']
    # All other possible pairs were skipped more recently too.
    for pair in (('b', 'c'), ('b', 'd'), ('c', 'd')):
        lobby.skip_sequence += 1
        lobby.skipped[frozenset(pair)] = lobby.skip_sequence
    await lobby.pair()
    assert lobby.matches['a'][0] == 'b'  # Oldest skip, despite queue order.
    match = lobby.matches['a'][1]
    await lobby.message('a', {'type': 'next', 'matchId': match})
    lobby.matches.clear()
    lobby.queue = ['b', 'd', 'c', 'a']
    await lobby.pair()
    assert lobby.matches['a'][0] == 'c'  # Re-skipping B moves it to last.


@pytest.mark.asyncio
async def test_unskipped_partner_wins_and_skip_is_batched():
    lobby = Lobby()
    lobby.matches = {'a': ('b', 'old'), 'b': ('a', 'old')}
    lobby.queue = ['c']
    lobby.skipped[frozenset(('b', 'c'))] = 1
    lobby.skip_sequence = 1
    await lobby.message('a', {'type': 'next', 'matchId': 'old'})
    assert lobby.matches['a'][0] == 'c'  # Never skipped, beats older B/C skip.
    assert lobby.queue == ['b']
    await lobby.message('a', {'type': 'stop'})
    assert frozenset(('a', 'c')) not in lobby.skipped  # Stop isn't a skip.


@pytest.mark.asyncio
async def test_equal_priority_uses_queue_order():
    lobby = Lobby()
    lobby.queue = ['a', 'b', 'c', 'd', 'e']
    await lobby.pair()
    assert lobby.matches['a'][0] == 'b'
    assert lobby.matches['c'][0] == 'd'
    assert lobby.queue == ['e']

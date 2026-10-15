import pytest
from aiohttp.test_utils import TestClient, TestServer
from audit import Audit
from countries import Cities
from server import create_app


def city(ip):
    lat, lon = {'a': (52.37, 4.9), 'b': (52.37, 4.9), 'c': (40.71, -74)}.get(ip, (None, None))
    return {'city': 'Example' if lat is not None else None, 'region': None, 'latitude':lat, 'longitude':lon}


def test_all_time_dots_one_per_browser_latest_known_city(tmp_path, monkeypatch):
    monkeypatch.setattr(Cities, 'lookup', lambda self, ip: city(ip))
    path = str(tmp_path/'audit.sqlite3')
    audit = Audit(path)
    for n, (visitor, ip) in enumerate([('one','a'),('one','a'),('one','b'),('two','a'),('one','c'),('three','unknown'),('two','unknown'),('four','a')]):
        audit.visit(str(n), visitor, ip, 'private agent', 'private referrer')
    audit.session('a-session','0','one','a','test')
    audit.session('b-session','','two','c','test')
    audit.match('match','a-session','b-session')
    audit.close()
    restored = Audit(path)
    assert restored.visitor_points() == [{'latitude':40.71,'longitude':-74,'count':1}, {'latitude':52.37,'longitude':4.9,'count':2}]
    assert restored.logs('visits',0,'0')['rows'][0]['location']['city'] == 'Example'
    match=restored.logs('matches',0,'')['rows'][0]
    assert match['a_location']['latitude']==52.37 and match['b_location']['latitude']==40.71
    event=next(row for row in restored.logs('events',0,'')['rows'] if row['actor']=='a-session')
    assert event['location']['city']=='Example'
    restored.close()


@pytest.mark.asyncio
async def test_public_map_returns_only_anonymous_coordinate_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(Cities, 'lookup', lambda self, ip: city('a'))
    path = str(tmp_path/'audit.sqlite3')
    audit = Audit(path)
    audit.visit('private-visit', 'private-visitor', 'private-ip', 'private-agent', 'private-referrer')
    audit.close()
    async with TestClient(TestServer(create_app(path))) as client:
        response = await client.get('/api/visitor-map')
        assert response.status == 200
        assert await response.json() == {'points': [{'latitude':52.37,'longitude':4.9,'count':1}]}
        assert response.headers['Cache-Control'] == 'public, max-age=60'
        assert (await client.get('/world.json')).status == 200
        assert (await client.get('/world.js')).status == 200
        assert (await client.get('/admin/api/logs')).status == 401

import pytest
from aiohttp.test_utils import TestClient, TestServer
from audit import Audit
from countries import Countries
from server import create_app


def test_all_time_country_totals_deduplicate_browsers_across_ips(tmp_path, monkeypatch):
    monkeypatch.setattr(Countries, 'lookup', lambda self, ip: {'a':'NL','b':'NL','c':'US'}.get(ip))
    path = str(tmp_path/'audit.sqlite3')
    audit = Audit(path)
    for n, (visitor, ip) in enumerate([('one','a'),('one','a'),('one','b'),('two','a'),('one','c'),('three','unknown')]):
        audit.visit(str(n), visitor, ip, 'private agent', 'private referrer')
    audit.close()
    restored = Audit(path)
    assert restored.country_totals() == {'NL':2, 'US':1}
    restored.close()


@pytest.mark.asyncio
async def test_public_map_returns_only_aggregates(tmp_path, monkeypatch):
    monkeypatch.setattr(Countries, 'lookup', lambda self, ip: 'NL')
    path = str(tmp_path/'audit.sqlite3')
    audit = Audit(path)
    audit.visit('private-visit', 'private-visitor', 'private-ip', 'private-agent', 'private-referrer')
    audit.close()
    async with TestClient(TestServer(create_app(path))) as client:
        response = await client.get('/api/visitor-map')
        assert response.status == 200
        assert await response.json() == {'countries': {'NL':1}}
        assert response.headers['Cache-Control'] == 'public, max-age=60'
        assert (await client.get('/world.json')).status == 200
        assert (await client.get('/world.js')).status == 200
        assert (await client.get('/admin/api/logs')).status == 401

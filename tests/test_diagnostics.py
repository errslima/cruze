import re
import pytest
from aiohttp import CookieJar
from aiohttp.test_utils import TestClient, TestServer
from admin import password_hash
from server import create_app


@pytest.mark.asyncio
async def test_diagnostic_ownership_validation_and_admin_trail(monkeypatch, tmp_path):
    monkeypatch.setenv('CRUZE_ADMIN_PASSWORD_HASH', password_hash('test-password'))
    async with TestClient(TestServer(create_app(str(tmp_path/'audit.sqlite3'))), cookie_jar=CookieJar(unsafe=True)) as c:
        origin = str(c.make_url('/')).rstrip('/')
        page = await (await c.get('/')).text()
        visit = re.search('name="cruze-visit" content="([a-f0-9]+)"', page)[1]
        payload = {'visit': visit, 'kind': 'media_error', 'detail': {'error': 'NotAllowedError', 'elapsed_ms': 123, 'sdp': 'private', 'ip': 'private'}}
        assert (await c.post('/diagnostics', json=payload)).status == 403
        headers = {'Origin': origin}
        assert (await c.post('/diagnostics', headers=headers, json={**payload, 'visit':'0'*32})).status == 403
        assert (await c.post('/diagnostics', headers=headers, json={**payload, 'kind':'invented'})).status == 400
        assert (await c.post('/diagnostics', headers=headers, json={**payload, 'match':'unrelated'})).status == 400
        assert (await c.post('/diagnostics', headers=headers, json=payload)).status == 204
        assert (await c.get('/admin/api/logs?kind=diagnostics')).status == 401
        await c.post('/admin/login', headers=headers, json={'password':'test-password'})
        data = await (await c.get('/admin/api/logs', params={'kind':'diagnostics','q':visit})).json()
        assert data['total'] == 1
        row = data['rows'][0]
        assert row['kind'] == 'media_error' and row['visit'] == visit
        import json
        assert json.loads(row['detail']) == {'error':'NotAllowedError', 'elapsed_ms':123}
        for _ in range(89):
            assert (await c.post('/diagnostics', headers=headers, json=payload)).status == 204
        assert (await c.post('/diagnostics', headers=headers, json=payload)).status == 429

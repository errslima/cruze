"""Exercise real startup/ICE telemetry, permission rejection and the admin trail."""
import asyncio
import os
import tempfile
from pathlib import Path
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright, expect
from admin import password_hash
from server import create_app

async def main():
    os.environ['CRUZE_ADMIN_PASSWORD_HASH'] = password_hash('test-password')
    with tempfile.TemporaryDirectory() as directory:
        async with TestServer(create_app(str(Path(directory)/'audit.sqlite3'))) as server, async_playwright() as p:
            url = str(server.make_url('/')).rstrip('/')
            browser = await p.chromium.launch(args=['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream','--autoplay-policy=no-user-gesture-required'])
            admin = await browser.new_page()
            await admin.goto(url+'/admin')
            await admin.locator('#password').fill('test-password')
            await admin.locator('button[type=submit]').click()
            await admin.get_by_role('heading', name='Activity log').wait_for()
            contexts = []
            pages = []
            for _ in range(2):
                ctx = await browser.new_context(permissions=['camera','microphone'])
                contexts.append(ctx)
                page = await ctx.new_page()
                await page.goto(url)
                await page.locator('#confirm-age').click()
                await page.locator('#start').click()
                pages.append(page)
            print('Browser peers started', flush=True)
            for page in pages:
                await expect(page.locator('#connection')).to_have_text('CONNECTED', timeout=30000)
                await page.evaluate('diagnosticQueue')
            print('Connection reports delivered', flush=True)
            visit = await pages[0].locator('meta[name=cruze-visit]').get_attribute('content')
            response = await admin.request.get(url+'/admin/api/logs', params={'kind':'diagnostics','q':visit})
            rows = (await response.json())['rows']
            kinds = {row['kind'] for row in rows}
            assert {'page_ready','start_clicked','media_allowed','signaling_open','waiting','matched','connected','ice_state'} <= kinds, kinds
            import json
            assert any('local_type' in json.loads(row['detail']) for row in rows)
            # Permission denial before a websocket opens must still reach the server.
            print('Connection diagnostics verified', flush=True)
            denied = await browser.new_context()
            await denied.add_init_script("navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('denied', 'NotAllowedError'); };")
            page = await denied.new_page()
            await page.goto(url)
            await page.locator('#confirm-age').click()
            await page.locator('#start').click()
            await expect(page.locator('#connection')).to_have_text('ERROR')
            await page.evaluate('diagnosticQueue')
            denied_visit = await page.locator('meta[name=cruze-visit]').get_attribute('content')
            response = await admin.request.get(url+'/admin/api/logs',params={'kind':'diagnostics','q':denied_visit})
            rows = (await response.json())['rows']
            assert any(row['kind']=='media_error' and json.loads(row['detail'])['error']=='NotAllowedError' for row in rows)
            print('Permission denial verified', flush=True)
            await admin.locator('#query').fill(denied_visit)
            await admin.locator('#search button').click()
            await admin.get_by_role('button',name='View trail',exact=True).click()
            await admin.get_by_role('cell',name='media error',exact=True).wait_for()
            await admin.screenshot(path='/tmp/cruze-diagnostics.png',full_page=True)
            # Force a timed-out attempt and verify the reason stays linked to its match.
            await pages[0].evaluate("fail('Test timeout', 'setup_timeout')")
            await pages[0].evaluate('diagnosticQueue')
            response = await admin.request.get(url+'/admin/api/logs', params={'kind':'diagnostics','q':visit})
            rows = (await response.json())['rows']
            assert any(row['kind']=='setup_timeout' and row['match_id'] for row in rows)
            await browser.close()
    print('PASS: real P2P diagnostics, candidate stats, permission denial before signaling, per-visit admin trail, timeout association')
asyncio.run(main())

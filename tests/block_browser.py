"""Check block confirmation, persistent cookie, and stale-popup behavior."""
import asyncio
import json
import time
from urllib.parse import unquote
from playwright.async_api import async_playwright
from static_stub import serve


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={'width': 390, 'height': 844})
        page = await context.new_page()
        await page.route('http://localhost:8001/**', serve)
        await page.goto('http://localhost:8001/')
        await page.locator('#confirm-age').click()
        await page.evaluate('''() => {
          active = true; peerIp = '192.0.2.2'; matchId = 'first';
          window.sent = [];
          socket = {readyState: WebSocket.OPEN, send: data => window.sent.push(JSON.parse(data)), close() {}};
          controls();
        }''')
        await page.locator('#block').click()
        assert await page.locator('#block-dialog').is_visible()
        await page.locator('#cancel-block').click()
        assert not any(c['name'] == 'cruze_blocks' for c in await context.cookies())
        assert not await page.evaluate('window.sent.length')
        await page.locator('#block').click()
        # Partner changes while confirmation is open: keep the original target.
        await page.evaluate("peerIp = '192.0.2.3'; matchId = 'second'")
        await page.locator('#confirm-block').click()
        assert await page.evaluate('window.sent[0]') == {'type': 'block', 'ip': '192.0.2.2', 'matchId': 'first'}
        assert await page.evaluate('matchId') == 'second'
        cookie = next(c for c in await context.cookies() if c['name'] == 'cruze_blocks')
        assert abs(cookie['expires'] - time.time() - 31536000) < 60
        assert '192.0.2.2' in json.loads(unquote(cookie['value']))
        await page.screenshot(path='/tmp/cruze-block-controls.png')
        box = await page.locator('.controls').bounding_box()
        assert box['x'] >= 0 and box['x'] + box['width'] <= 390
        await page.locator('#block').click()
        await page.screenshot(path='/tmp/cruze-block-popup.png')
        await page.locator('#confirm-block').click()
        assert await page.evaluate('matchId === null')
        await page.reload()
        assert set(await page.evaluate('Object.keys(savedBlocks())')) == {'192.0.2.2', '192.0.2.3'}
        await browser.close()
        print('PASS: cancel, confirmation, one-year cookie, stale popup, disconnect, reload, mobile controls')


asyncio.run(main())

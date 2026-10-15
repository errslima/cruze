"""Run manually: uv run python tests/browser_smoke.py (server must be running)."""
import asyncio
import time
from playwright.async_api import async_playwright


async def wait_for(page, expression, timeout=30000):
    async with asyncio.timeout(timeout / 1000):
        while not await page.evaluate(expression):
            await asyncio.sleep(.1)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(timeout=30000, args=[
            '--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
            '--autoplay-policy=no-user-gesture-required',
        ])
        errors = []
        contexts = [await browser.new_context(permissions=['camera', 'microphone']) for _ in range(3)]
        pages = [await context.new_page() for context in contexts]
        for page in pages:
            page.on('pageerror', lambda error: errors.append(str(error)))
            await page.goto('http://127.0.0.1:8000/')
        a, b, c = pages
        assert await a.locator('#age-gate').is_visible()
        assert await a.locator('#start').is_disabled()
        await a.keyboard.press('Escape')
        assert await a.locator('#age-gate').is_visible()
        await a.screenshot(path='/tmp/cruze-age-gate.png', full_page=True)
        for page in pages:
            await page.locator('#confirm-age').click()
        cookie = next(c for c in await contexts[0].cookies() if c['name'] == 'cruze_adult')
        assert abs(cookie['expires'] - time.time() - 31536000) < 60
        assert cookie['sameSite'] == 'Lax'
        await a.reload()
        assert not await a.locator('#age-gate').is_visible()
        assert await a.evaluate('stream == null')
        await a.screenshot(path='/tmp/cruze-desktop.png', full_page=True)
        for page in (a, b):
            await page.locator('#start').click()
        for page in (a, b):
            await wait_for(page, "document.getElementById('connection').textContent === 'CONNECTED'")
            await wait_for(page, "document.getElementById('remote').videoWidth > 0")
            candidates = await page.evaluate('''async () => {
                const stats = await peer.getStats();
                const transport = [...stats.values()].find(s => s.type === 'transport' && s.selectedCandidatePairId);
                const pair = stats.get(transport.selectedCandidatePairId);
                return [stats.get(pair.localCandidateId).candidateType, stats.get(pair.remoteCandidateId).candidateType];
            }''')
            assert 'relay' not in candidates, candidates
            print('Direct candidate pair:', candidates)
        await a.locator('#mic').click()
        assert await a.evaluate('stream.getAudioTracks()[0].enabled') is False
        await a.locator('#camera').click()
        assert await a.evaluate('stream.getVideoTracks()[0].enabled') is False
        await c.locator('#start').click()
        await wait_for(c, "document.getElementById('connection').textContent === 'WAITING'")
        await a.locator('#next').click()
        for page in (b, c):
            await wait_for(page, "document.getElementById('connection').textContent === 'CONNECTED'")
        await a.locator('#stop').click()
        assert await a.evaluate('stream == null && peer === null')
        await b.close()
        await wait_for(c, "document.getElementById('connection').textContent === 'WAITING'")
        await c.locator('#stop').click()
        await a.set_viewport_size({'width':390, 'height':844})
        await a.screenshot(path='/tmp/cruze-mobile.png', full_page=True)
        assert await a.evaluate('document.documentElement.scrollWidth <= innerWidth')
        # Force an impossible route to exercise the no-relay failure path.
        await a.evaluate("rtcConfig.iceServers = []; rtcConfig.iceTransportPolicy = 'relay'")
        for page in (a, c):
            await page.locator('#start').click()
        # Either peer may time out first; its partner then returns to the queue.
        async with asyncio.timeout(22):
            while 'CONNECTION FAILED' not in [await page.locator('#connection').text_content() for page in (a, c)]:
                await asyncio.sleep(.1)
        for page in (a, c):
            await wait_for(page, 'peer === null')
        for page in (a, c):
            await page.locator('#stop').click()
        await contexts[0].clear_cookies()
        await a.reload()
        assert await a.locator('#age-gate').is_visible()
        await a.locator('#leave').click()
        assert a.url == 'about:blank'
        assert not await contexts[0].cookies()
        assert not errors, errors
        print('PASS: age popup, one-year cookie, returning visits, decline, video, direct candidates, controls, skip, disconnect, camera cleanup, mobile layout, timeout; no browser errors.')
        await browser.close()


asyncio.run(main())

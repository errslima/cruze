"""Run manually: uv run python tests/browser_smoke.py (server must be running)."""
import asyncio
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
        await a.screenshot(path='/tmp/cruze-desktop.png', full_page=True)
        await a.locator('#start').click()
        assert 'Confirm' in await a.locator('#status').inner_text()
        for page in (a, b):
            await page.locator('#consent').check()
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
        await c.locator('#consent').check()
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
        await wait_for(a, "document.getElementById('connection').textContent === 'CONNECTION FAILED'", timeout=22000)
        assert await a.evaluate('peer === null')
        for page in (a, c):
            await page.locator('#stop').click()
        assert not errors, errors
        print('PASS: video, direct candidates, controls, skip, disconnect, camera cleanup, mobile layout, timeout; no browser errors.')
        await browser.close()


asyncio.run(main())

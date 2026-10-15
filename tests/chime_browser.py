"""Run manually: uv run python tests/chime_browser.py (server must be running)."""
import asyncio
from playwright.async_api import async_playwright

# Each chime starts two short tones; count them instead of listening.
COUNT_TONES = '''
window.tones = 0;
const create = AudioContext.prototype.createOscillator;
AudioContext.prototype.createOscillator = function () { window.tones++; return create.call(this); };
'''


async def wait_for(page, expression, timeout=30000):
    async with asyncio.timeout(timeout / 1000):
        while not await page.evaluate(expression):
            await asyncio.sleep(.1)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'])
        contexts = [await browser.new_context(permissions=['camera', 'microphone']) for _ in range(2)]
        a, b = [await context.new_page() for context in contexts]
        for page in (a, b):
            await page.add_init_script(COUNT_TONES)
            await page.goto('http://127.0.0.1:8000/')
            await page.locator('#confirm-age').click()
        await a.locator('#start').click()
        await wait_for(a, "document.getElementById('connection').textContent === 'WAITING'")
        await asyncio.sleep(.5)
        assert await a.evaluate('tones') == 0, 'No chime while waiting'
        await b.locator('#start').click()
        for page in (a, b):
            await wait_for(page, 'tones === 2')
            assert await page.evaluate("chimeAudio.state") == 'running'
        await a.locator('#next').click()
        for page in (a, b):
            await wait_for(page, 'tones === 4')
        await a.locator('#stop').click()
        await wait_for(b, "document.getElementById('connection').textContent === 'WAITING'")
        await asyncio.sleep(.5)
        assert await b.evaluate('tones') == 4, 'Partner leaving is not a match'
        await browser.close()
    print('Chime checks passed.')


asyncio.run(main())

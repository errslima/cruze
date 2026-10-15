"""Run manually: uv run python tests/lobby_browser.py (server must be running)."""
import asyncio
from playwright.async_api import async_playwright


async def wait_for(page, expression, timeout=10000):
    async with asyncio.timeout(timeout / 1000):
        while not await page.evaluate(expression):
            await asyncio.sleep(.1)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        errors = []
        desktop = await browser.new_context(viewport={'width': 1280, 'height': 800})
        phone = await browser.new_context(viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
        a, b = await desktop.new_page(), await phone.new_page()
        for page in (a, b):
            page.on('pageerror', lambda error: errors.append(str(error)))
            await page.goto('http://127.0.0.1:8000/')
        # Nothing connects before the 18+ confirmation.
        assert await a.locator('#lobby-count').text_content() == 'Connecting…'
        assert await a.locator('#lobby-input').is_disabled()
        for page in (a, b):
            await page.locator('#confirm-age').click()
            await wait_for(page, "!document.getElementById('lobby-input').disabled")
        # Wide screens open the lobby by default; phones start with it closed.
        assert await a.locator('#lobby').is_visible() and not await a.locator('#lobby-toggle').is_visible()
        assert not await b.locator('#lobby').is_visible() and await b.locator('#lobby-toggle').is_visible()
        await wait_for(a, "document.getElementById('lobby-count').textContent === '2 people here'")
        me = await a.locator('#lobby-me').text_content()
        assert me.startswith('You appear as ')
        text = 'hello <b>lobby</b> ' + '🙂'
        await a.locator('#lobby-input').fill(text)
        await a.locator('#lobby-input').press('Enter')
        await wait_for(a, "document.querySelectorAll('#lobby-messages li.mine').length === 1")
        assert await a.locator('#lobby-input').input_value() == ''
        # Text renders literally, and a closed lobby shows an unread dot.
        await wait_for(b, "!document.getElementById('lobby-unread').hidden")
        await b.locator('#lobby-toggle').click()
        assert await b.locator('#lobby-unread').is_hidden()
        last = b.locator('#lobby-messages li').last
        assert await last.locator('p').text_content() == text
        assert await last.get_attribute('class') != 'mine'
        assert await b.locator('#lobby-messages b').count() == 0
        await b.locator('#lobby-input').fill('hi from my phone')
        await b.locator('#lobby-send').click()
        await wait_for(a, "document.querySelector('#lobby-messages li:last-child p').textContent === 'hi from my phone'")
        # The panel stays clear of the call controls and self-preview.
        for page in (a, b):
            lobby, controls, preview = [await page.locator(s).bounding_box() for s in ('#lobby', '.controls', '.preview')]
            assert lobby['y'] + lobby['height'] <= controls['y'], 'lobby overlaps controls'
            assert lobby['y'] >= preview['y'] + preview['height'] or lobby['x'] + lobby['width'] <= preview['x'], 'lobby overlaps preview'
            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        await a.screenshot(path='/tmp/cruze-lobby-desktop.png')
        await b.screenshot(path='/tmp/cruze-lobby-mobile.png')
        # The open/closed choice is remembered; history returns after reload.
        await b.locator('#lobby-close').click()
        await b.reload()
        await wait_for(b, "!document.getElementById('lobby-input').disabled")
        assert not await b.locator('#lobby').is_visible()
        assert await b.locator('#lobby-messages li').count() >= 2
        await wait_for(a, "document.getElementById('lobby-count').textContent === '2 people here'")
        await b.close()
        await wait_for(a, "document.getElementById('lobby-count').textContent === 'Just you right now'")
        assert not errors, errors
        await browser.close()
    print('PASS: age gate, default open state, send, live delivery, literal text, unread dot, layout, remembered state, history, presence count')


asyncio.run(main())

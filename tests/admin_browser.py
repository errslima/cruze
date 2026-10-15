"""Private dashboard and client-reported timing end-to-end, on an isolated server."""
import asyncio
import os
import tempfile
from pathlib import Path

from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright
from admin import password_hash
from audit import Audit
from server import create_app


async def until(page, expression):
    async with asyncio.timeout(30):
        while not await page.evaluate(expression):
            await asyncio.sleep(.1)


async def main():
    os.environ['CRUZE_ADMIN_PASSWORD_HASH'] = password_hash('browser-test-password')
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / 'audit.sqlite3')
        data = Audit(path)
        for n in range(105):
            data.visit(str(n), f'visitor-{n}', f'192.0.2.{n + 1}', 'Example Browser 1.0', '')
        data.visit('xss', 'visitor-xss', '198.51.100.1', '<img src=x onerror=alert(1)>', '')
        data.close()
        async with TestServer(create_app(path)) as server:
            url = str(server.make_url('/')).rstrip('/')
            async with async_playwright() as p:
                browser = await p.chromium.launch(args=['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', '--autoplay-policy=no-user-gesture-required'])
                context = await browser.new_context()
                page = await context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                confirmations = []
                async def dialog(dialog):
                    if confirmations:
                        confirmations.pop()
                        await dialog.accept()
                    else:
                        errors.append('Unexpected browser dialog')
                        await dialog.dismiss()
                page.on('dialog', dialog)
                await page.goto(url + '/admin')
                assert await page.locator('#password').is_visible()
                assert (await context.request.get(url + '/admin/api/logs')).status == 401
                await page.locator('#password').fill('browser-test-password')
                await page.locator('button[type=submit]').click()
                await page.locator('#rows tr').first.wait_for()
                assert await page.locator('#rows tr').count() == 100
                assert await page.locator('#rows img').count() == 0
                assert await page.get_by_role('columnheader', name='Country', exact=True).count() == 1
                assert await page.get_by_role('columnheader', name='Estimated city / region', exact=True).count() == 1
                assert await page.locator('#rows tr').first.locator('td').nth(3).inner_text() == 'Unknown'
                assert await page.locator('#rows tr').first.locator('td').nth(2).inner_text() == '—'
                await page.screenshot(path='/tmp/cruze-admin-desktop.png', full_page=True)
                await page.locator('#next').click()
                await until(page, "document.getElementById('page').textContent.includes('101–106')")
                await page.locator('#query').fill('198.51.100.1')
                await page.locator('#search button').click()
                await until(page, "document.getElementById('page').textContent === '1–1 of 1'")
                # Two real browser WebRTC sessions report their connected state.
                callers = []
                for _ in range(2):
                    caller_context = await browser.new_context(permissions=['camera', 'microphone'])
                    caller = await caller_context.new_page()
                    await caller.goto(url)
                    await caller.locator('#confirm-age').click()
                    await caller.locator('#start').click()
                    callers.append(caller)
                for caller in callers:
                    await until(caller, "document.getElementById('connection').textContent === 'CONNECTED'")
                await asyncio.sleep(.2)
                await callers[0].locator('#stop').click()
                await callers[1].locator('#stop').click()
                await page.locator('#query').fill('')
                await page.locator('#search button').click()
                await page.locator('[data-kind=matches]').click()
                await until(page, "document.getElementById('rows').textContent.includes('stop')")
                assert 'Not connected' not in await page.locator('#rows').inner_text()
                await page.screenshot(path='/tmp/cruze-admin-matches.png', full_page=True)
                # Lobby messages are listed with their sender and can be removed for everyone.
                caller = callers[0]
                await until(caller, "!document.getElementById('lobby-input').disabled")
                await caller.locator('#lobby-input').fill('<i>spam</i>')
                await caller.locator('#lobby-input').press('Enter')
                await until(caller, "document.querySelectorAll('#lobby-messages li').length === 1")
                await page.locator('[data-kind=chat]').click()
                await until(page, "document.getElementById('rows').textContent.includes('<i>spam</i>')")
                assert await page.locator('#rows i').count() == 0
                assert await page.get_by_role('columnheader', name='Message', exact=True).count() == 1
                confirmations.append(True)
                await page.locator('#rows button', has_text='Remove').click()
                await until(page, "document.getElementById('rows').textContent.includes('Removed')")
                await until(caller, "document.querySelectorAll('#lobby-messages li').length === 0")
                assert not confirmations
                await page.set_viewport_size({'width':390,'height':844})
                await page.screenshot(path='/tmp/cruze-admin-mobile.png', full_page=True)
                assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                await page.locator('#logout').click()
                await page.locator('#password').wait_for()
                assert (await context.request.get(url + '/admin/api/logs')).status == 401
                assert not errors, errors
                await browser.close()
    print('PASS: private dashboard, pagination, search, escaped visitor text, actual WebRTC timing, lobby chat removal, mobile layout, logout')


asyncio.run(main())

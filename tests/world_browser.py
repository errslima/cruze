"""Map rendering, mobile layout, errors, and transition into a real P2P call."""
import asyncio
import tempfile
from pathlib import Path
from aiohttp.test_utils import TestServer
from playwright.async_api import async_playwright, expect
from audit import Audit
from countries import Cities
from server import create_app

async def main():
    original = Cities.lookup
    locations = {'nl':(52.37,4.9),'us':(40.71,-74),'br':(-23.55,-46.63),'au':(-33.87,151.21),'jp':(35.68,139.69)}
    def lookup(self, ip):
        lat,lon=locations.get(ip,(None,None))
        return {'city':ip if lat is not None else None,'region':None,'latitude':lat,'longitude':lon}
    Cities.lookup = lookup
    try:
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory)/'audit.sqlite3')
            audit = Audit(path)
            for code, count in [('nl',20),('us',100),('br',6),('au',2),('jp',9)]:
                for n in range(count):
                    audit.visit(f'{code}-{n}', f'{code}-{n}', code, '', '')
            audit.close()
            async with TestServer(create_app(path)) as server, async_playwright() as p:
                browser = await p.chromium.launch(args=['--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream','--autoplay-policy=no-user-gesture-required'])
                contexts=[]
                errors=[]
                async def caller():
                    context=await browser.new_context(permissions=['camera','microphone'])
                    contexts.append(context)
                    page=await context.new_page()
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    await page.goto(str(server.make_url('/')))
                    await page.locator('#confirm-age').click()
                    await page.locator('#start').click()
                    return page
                a=await caller()
                await expect(a.locator('#world')).to_have_class('is-visible')
                await expect(a.locator('#visitor-dots circle')).to_have_count(5)
                assert await a.locator('#world-map path').count() > 150
                assert await a.locator('#visitor-dots circle').evaluate_all('(nodes) => nodes.reduce((sum, el) => sum + Number(el.dataset.visitors), 0)') == 137
                assert await a.locator('#visitor-dots circle[data-visitors="100"]').count() == 1
                await expect(a.locator('#connection')).to_have_text('WAITING')
                await a.screenshot(path='/tmp/cruze-world-desktop.png', animations='disabled')
                await a.set_viewport_size({'width':390,'height':844})
                await a.screenshot(path='/tmp/cruze-world-mobile.png', animations='disabled')
                # Dense overlap has higher alpha than sparse locations.
                assert await a.locator('#world-map defs radialGradient').count() == 5
                assert await a.evaluate('''() => {
                    const alpha = count => {
                        const circle = document.querySelector(`#visitor-dots circle[data-visitors="${count}"]`);
                        const id = circle.getAttribute('fill').slice(5, -1);
                        return Number(document.getElementById(id).children[12].getAttribute('stop-opacity'));
                    };
                    return alpha(100) > alpha(20) && alpha(20) > alpha(2);
                }''')
                await a.set_viewport_size({'width':844,'height':390})
                await a.screenshot(path='/tmp/cruze-world-landscape.png', animations='disabled')
                await a.set_viewport_size({'width':390,'height':844})
                assert await a.evaluate('document.documentElement.scrollWidth <= innerWidth')
                world=await a.locator('#world-map').bounding_box()
                controls=await a.locator('.controls').bounding_box()
                assert world['x'] >= 0 and world['x']+world['width'] <= 390
                assert world['y']+world['height'] < controls['y']
                b=await caller()
                for page in (a,b):
                    await expect(page.locator('#connection')).to_have_text('CONNECTED', timeout=30000)
                    await expect(page.locator('#world')).not_to_have_class('is-visible')
                await b.locator('#stop').click()
                await expect(a.locator('#world')).to_have_class('is-visible')
                await expect(a.locator('#world-status')).to_have_text('Finding someone')
                await a.locator('#stop').click()
                await expect(a.locator('#world')).not_to_have_class('is-visible')
                # A failed map request must leave matchmaking and the base map usable.
                context=await browser.new_context(permissions=['camera','microphone'], reduced_motion='reduce')
                await context.route('**/api/visitor-map', lambda route: route.fulfill(status=503))
                page=await context.new_page()
                await page.goto(str(server.make_url('/')))
                await page.locator('#confirm-age').click()
                await page.locator('#start').click()
                await expect(page.locator('#world-note')).to_have_text('Visitor map temporarily unavailable')
                await expect(page.locator('#connection')).to_have_text('WAITING')
                assert await page.locator('.world-dots').evaluate('(el) => getComputedStyle(el).animationName') == 'none'
                assert not errors, errors
                await browser.close()
        print('PASS: map heat, desktop/mobile fit, P2P video transitions, stop/skip waiting, failed map fetch, reduced motion')
    finally:
        Cities.lookup=original
asyncio.run(main())

"""Playback races, using browser media elements with controlled play outcomes."""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright


async def main():
    root = Path(__file__).resolve().parents[1]
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        # Serve working-tree assets without needing a live signaling server.
        async def serve(route):
            name = route.request.url.split('/')[-1] or 'index.html'
            mime = {'index.html': 'text/html', 'app.js': 'text/javascript', 'style.css': 'text/css'}
            await route.fulfill(path=root / 'static' / name, content_type=mime[name])
        await page.route('http://localhost:8001/**', serve)
        await page.goto('http://localhost:8001/')
        await page.evaluate('''async () => {
          const check = (ok, message) => { if (!ok) throw new Error(message); };
          stream = new MediaStream();
          await matched({matchId: 'test', initiator: false});
          const incoming = new MediaStream();
          let calls = 0;
          ui.remote.play = () => { calls++; return Promise.reject(new DOMException('Interrupted', 'AbortError')); };
          peer.ontrack({streams: [incoming]});
          peer.ontrack({streams: [incoming]});
          await Promise.resolve();
          check(calls === 1, 'Audio/video events must attach the shared stream only once');
          check(ui.play.hidden, 'Interrupted playback must not show a play button');
          Object.defineProperty(ui.remote, 'paused', {configurable: true, get: () => true});
          ui.remote.play = () => Promise.reject(new DOMException('Gesture required', 'NotAllowedError'));
          await playRemote();
          check(!ui.play.hidden, 'Genuinely blocked autoplay must offer a play button');
          Object.defineProperty(ui.remote, 'paused', {configurable: true, get: () => false});
          ui.remote.dispatchEvent(new Event('playing'));
          check(ui.play.hidden, 'Playback starting independently must clear the fallback');
          await playRemote();
          check(ui.play.hidden, 'Late rejection must not cover playing video');
          ui.play.hidden = false;
          ui.remote.play = () => Promise.resolve();
          await ui.play.onclick();
          check(ui.play.hidden, 'Successful user retry must hide the button');
          let reject;
          ui.remote.play = () => new Promise((_, fail) => { reject = fail; });
          const pending = playRemote();
          closePeer();
          reject(new DOMException('Old call blocked', 'NotAllowedError'));
          await pending;
          check(ui.play.hidden, 'Old call failures must not affect the next call');
        }''')
        await browser.close()
        print('PASS: shared tracks, AbortError, blocked autoplay, playing event, late rejection, retry, old call cleanup')


asyncio.run(main())

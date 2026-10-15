"""Exercise webcam selection with synthetic video tracks and a real RTP sender."""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright


async def main():
    root = Path(__file__).resolve().parents[1]
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={'width': 320, 'height': 720})
        async def serve(route):
            name = route.request.url.split('/')[-1] or 'index.html'
            await route.fulfill(path=root / 'static' / name, content_type={
                'index.html': 'text/html', 'app.js': 'text/javascript', 'style.css': 'text/css'}[name])
        await page.route('http://localhost:8001/**', serve)
        await page.goto('http://localhost:8001/')
        await page.locator('#confirm-age').click()
        await page.evaluate('''async () => {
          window.check = (ok, message) => { if (!ok) throw new Error(message); };
          window.makeTrack = id => {
            const canvas = document.createElement('canvas'); canvas.width = 640; canvas.height = 480;
            canvas.getContext('2d').fillRect(0, 0, 640, 480);
            const track = canvas.captureStream(10).getVideoTracks()[0];
            const settings = track.getSettings.bind(track);
            track.getSettings = () => ({...settings(), deviceId: id});
            return track;
          };
          window.devices = [{kind: 'videoinput', deviceId: 'front', label: 'Front webcam'},
                            {kind: 'videoinput', deviceId: 'usb', label: 'USB webcam'}];
          navigator.mediaDevices.enumerateDevices = async () => window.devices;
          navigator.mediaDevices.getUserMedia = async constraints => {
            const id = constraints.video.deviceId?.exact || 'front';
            if (id === 'missing') throw new DOMException('Unavailable', 'OverconstrainedError');
            return new MediaStream([makeTrack(id)]);
          };
          window.audioContext = new AudioContext();
          window.audio = audioContext.createMediaStreamDestination().stream.getAudioTracks()[0];
          window.original = makeTrack('front');
          stream = new MediaStream([original, audio]); ui.local.srcObject = stream;
          active = true; peer = new RTCPeerConnection();
          window.videoSender = peer.addTrack(original, stream); peer.addTrack(audio, stream);
          await refreshCameras(); controls();
        }''')
        assert await page.locator('#camera-select option').all_text_contents() == ['Default camera', 'Front webcam', 'USB webcam']
        await page.locator('#camera-select').select_option('usb')
        for _ in range(100):
            if not await page.evaluate('switchingCamera'):
                break
            await asyncio.sleep(.02)
        await page.evaluate('''async () => {
          check(videoSender.track === stream.getVideoTracks()[0], 'The live sender must receive the new track');
          check(videoSender.track.getSettings().deviceId === 'usb', 'Selected USB webcam');
          check(original.readyState === 'ended', 'Old webcam must be released');
          check(stream.getAudioTracks()[0] === audio && audio.readyState === 'live', 'Microphone must be preserved');
          check(localStorage.getItem('cruze_camera') === 'usb', 'Selection must be remembered');
          ui.camera.click();
          await switchCamera('front');
          check(!videoSender.track.enabled, 'Camera-off must survive switching');
          await switchCamera('missing');
          check(videoSender.track.getSettings().deviceId === 'front', 'Failed switch keeps old camera');
          check(!$('camera-error').hidden, 'Failed switch is explained');
          const fallback = await openCamera('missing', true);
          check(fallback.getVideoTracks()[0].getSettings().deviceId === 'front', 'Unplugged saved camera falls back');
          fallback.getTracks().forEach(track => track.stop());
          // Stop while permission/device acquisition is pending must release the new camera.
          let resolve;
          navigator.mediaDevices.getUserMedia = () => new Promise(done => { resolve = done; });
          const pending = switchCamera('usb');
          stop();
          const late = makeTrack('usb'); resolve(new MediaStream([late]));
          await pending;
          check(late.readyState === 'ended' && stream === null, 'Stop during switch must not leak camera access');
          window.devices = [window.devices[0]];
          navigator.mediaDevices.dispatchEvent(new Event('devicechange'));
          await refreshCameras();
          check(cameraSelect.options.length === 2, 'Unplugged cameras leave the menu');
          await audioContext.close();
        }''')
        box = await page.locator('.controls').bounding_box()
        assert box['x'] >= 0 and box['x'] + box['width'] <= 320
        await page.screenshot(path='/tmp/cruze-camera-mobile.png')
        await page.reload()
        assert await page.evaluate('preferredCamera') == 'front'
        await browser.close()
        print('PASS: webcam menu, live RTP track replacement, microphone preservation, camera-off, persistence, failure fallback, stop race, unplug, mobile layout')


asyncio.run(main())

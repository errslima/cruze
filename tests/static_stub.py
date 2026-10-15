"""Serve the page's static files to Playwright without the Python server."""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / 'static'
TYPES = {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json'}


async def serve(route):
    name = route.request.url.split('?')[0].split('/')[-1] or 'index.html'
    if name == 'visitor-map':
        await route.fulfill(json={'points': []})
    elif (STATIC / name).is_file():
        await route.fulfill(path=STATIC / name, content_type=TYPES[(STATIC / name).suffix])
    else:
        await route.fulfill(status=404)

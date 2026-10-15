"""Bounded, same-origin browser diagnostics linked to an existing page visit."""
import json
import os
import time
from aiohttp import web

KINDS = {'page_ready', 'start_clicked', 'media_allowed', 'media_error', 'media_unsupported',
         'signaling_open', 'signaling_error', 'signaling_timeout', 'signaling_closed',
         'waiting', 'matched', 'ice_state', 'ice_gathering_complete', 'stun_error',
         'connected', 'disconnected', 'failed', 'setup_timeout', 'setup_error', 'connection_lost', 'stopped', 'skipped', 'blocked', 'peer_left'}
VALUES = {
    'error': {'NotAllowedError', 'NotFoundError', 'NotReadableError', 'OverconstrainedError', 'AbortError', 'SecurityError', 'TypeError', 'UnknownError'},
    'ice': {'new', 'checking', 'connected', 'completed', 'failed', 'disconnected', 'closed'},
    'gathering': {'new', 'gathering', 'complete'},
    'local_type': {'host', 'srflx', 'prflx', 'relay'},
    'remote_type': {'host', 'srflx', 'prflx', 'relay'},
    'protocol': {'udp', 'tcp'},
    'reason': {'stop', 'page_closed', 'skip', 'block'},
}
NUMBERS = {'elapsed_ms', 'host_candidates', 'srflx_candidates', 'stun_code', 'bytes_sent', 'bytes_received'}


def install_diagnostics(app, audit):
    async def report(request):
        headers = {'Cache-Control': 'no-store'}
        if request.headers.get('Origin') != os.getenv('CRUZE_ORIGIN', f'{request.scheme}://{request.host}'):
            raise web.HTTPForbidden(headers=headers)
        if request.content_length is not None and request.content_length > 2048:
            raise web.HTTPRequestEntityTooLarge(max_size=2048, actual_size=request.content_length)
        try:
            data = await request.json()
            if not isinstance(data, dict) or data.get('kind') not in KINDS:
                raise ValueError()
            visit = data.get('visit')
            if not isinstance(visit, str) or len(visit) != 32:
                raise ValueError()
            owner = audit.db.execute('SELECT 1 FROM visits WHERE id=? AND visitor=?',
                                     (visit, request.cookies.get('cruze_visitor', ''))).fetchone()
            if not owner:
                raise web.HTTPForbidden(headers=headers)
            now = time.time()
            total, recent = audit.db.execute('SELECT count(*), coalesce(sum(at > ?),0) FROM diagnostics WHERE visit=?', (now-60, visit)).fetchone()
            if total >= 2000 or recent >= 90:
                raise web.HTTPTooManyRequests(headers=headers)
            detail = data.get('detail', {})
            if not isinstance(detail, dict):
                raise ValueError()
            clean = {k: v for k, v in detail.items() if k in VALUES and isinstance(v, str) and v in VALUES[k]}
            clean.update({k: int(v) for k, v in detail.items() if k in NUMBERS and type(v) in (int, float) and 0 <= v <= 10**12})
            match = data.get('match')
            if match is not None:
                if not isinstance(match, str) or not audit.db.execute('''SELECT 1 FROM matches m JOIN sessions s
                    ON (s.id=m.a OR s.id=m.b) WHERE m.id=? AND s.visit=?''', (match, visit)).fetchone():
                    raise ValueError()
            audit.db.execute('INSERT INTO diagnostics(visit,at,kind,detail,match_id) VALUES (?,?,?,?,?)',
                             (visit, now, data['kind'], json.dumps(clean), match))
            audit.db.commit()
        except (ValueError, TypeError):
            raise web.HTTPBadRequest(headers=headers)
        return web.Response(status=204, headers=headers)
    app.router.add_post('/diagnostics', report)

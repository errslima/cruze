"""Persistent metadata: visits, signaling sessions, call lifecycle and lobby text."""
import sqlite3
import time
from pathlib import Path
from countries import Countries, Cities


class Audit:
    def __init__(self, path):
        if path != ':memory:':
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.countries = Countries()
        self.cities = Cities()
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS visits (
                id TEXT PRIMARY KEY, visitor TEXT, ip TEXT, agent TEXT,
                referrer TEXT, at REAL);
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, visit TEXT, visitor TEXT, ip TEXT, agent TEXT,
                started REAL, ended REAL, reason TEXT);
            CREATE TABLE IF NOT EXISTS matches (
                id TEXT PRIMARY KEY, a TEXT, b TEXT, matched REAL, connected REAL,
                ended REAL, ended_by TEXT, reason TEXT,
                a_online INTEGER DEFAULT 0, b_online INTEGER DEFAULT 0,
                connected_since REAL, connected_seconds REAL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL, actor TEXT,
                match_id TEXT, kind TEXT);
            CREATE TABLE IF NOT EXISTS diagnostics (
                id INTEGER PRIMARY KEY AUTOINCREMENT, visit TEXT, at REAL,
                kind TEXT, detail TEXT, match_id TEXT);
            CREATE INDEX IF NOT EXISTS diagnostics_visit ON diagnostics(visit, at);
            CREATE INDEX IF NOT EXISTS diagnostics_at ON diagnostics(at DESC);
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value REAL);
            CREATE INDEX IF NOT EXISTS visits_at ON visits(at DESC);
            CREATE INDEX IF NOT EXISTS sessions_visit ON sessions(visit);
            CREATE INDEX IF NOT EXISTS matches_at ON matches(matched DESC);
            CREATE INDEX IF NOT EXISTS events_at ON events(at DESC);
            CREATE TABLE IF NOT EXISTS chat (
                id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL, visitor TEXT, ip TEXT,
                name TEXT, country TEXT, text TEXT, hidden INTEGER DEFAULT 0);
        ''')
        # After a crash, use the last heartbeat, not the later restart time.
        heartbeat = self.db.execute("SELECT value FROM metadata WHERE key='heartbeat'").fetchone()
        last = heartbeat[0] if heartbeat else time.time()
        for row in self.db.execute('SELECT id, matched, connected, connected_since FROM matches WHERE ended IS NULL').fetchall():
            self.end_match(row['id'], None, 'server_restart', max(last, row['matched'], row['connected'] or 0, row['connected_since'] or 0))
        self.db.execute("UPDATE sessions SET ended=MAX(started, ?), reason='server_restart' WHERE ended IS NULL", (last,))
        self.heartbeat()

    def heartbeat(self):
        self.db.execute("INSERT OR REPLACE INTO metadata VALUES ('heartbeat', ?)", (time.time(),))
        self.db.commit()

    def visit(self, ident, visitor, ip, agent, referrer):
        self.db.execute('INSERT INTO visits VALUES (?, ?, ?, ?, ?, ?)',
                        (ident, visitor, ip, agent[:1000], referrer[:1000], time.time()))
        self.db.commit()

    def session(self, ident, visit, visitor, ip, agent):
        # A tab supplies its page ID; only associate it with the same visitor.
        exists = self.db.execute('SELECT 1 FROM visits WHERE id=? AND visitor=?', (visit, visitor)).fetchone()
        self.db.execute('INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, NULL, NULL)',
                        (ident, visit if exists else None, visitor, ip, agent[:1000], time.time()))
        self.event(ident, None, 'session_open')

    def event(self, actor, match, kind):
        self.db.execute('INSERT INTO events(at, actor, match_id, kind) VALUES (?, ?, ?, ?)',
                        (time.time(), actor, match, kind))
        self.db.commit()

    def match(self, ident, a, b):
        self.db.execute('INSERT INTO matches(id, a, b, matched) VALUES (?, ?, ?, ?)', (ident, a, b, time.time()))
        self.event(None, ident, 'matched')

    def connection(self, ident, actor, state):
        row = self.db.execute('SELECT * FROM matches WHERE id=? AND ended IS NULL', (ident,)).fetchone()
        if not row or actor not in (row['a'], row['b']):
            return
        now = time.time()
        side = 'a_online' if row['a'] == actor else 'b_online'
        online = int(state == 'connected')
        if row[side] == online:
            return
        a = online if side == 'a_online' else row['a_online']
        b = online if side == 'b_online' else row['b_online']
        since, total, first = row['connected_since'], row['connected_seconds'], row['connected']
        if since is not None and not (a and b):
            total += max(0, now - since)
            since = None
        elif since is None and a and b:
            since = now
            first = first or now
        self.db.execute('''UPDATE matches SET a_online=?, b_online=?, connected_since=?,
                           connected_seconds=?, connected=? WHERE id=?''', (a, b, since, total, first, ident))
        self.event(actor, ident, state)

    def end_match(self, ident, actor, reason, now=None):
        now = time.time() if now is None else now
        row = self.db.execute('SELECT * FROM matches WHERE id=? AND ended IS NULL', (ident,)).fetchone()
        if not row:
            return
        total = row['connected_seconds']
        if row['connected_since'] is not None:
            total += max(0, now - row['connected_since'])
        self.db.execute('''UPDATE matches SET ended=?, ended_by=?, reason=?, connected_seconds=?,
                           connected_since=NULL WHERE id=?''', (now, actor, reason, total, ident))
        self.event(actor, ident, reason)

    def end_session(self, ident, reason):
        self.db.execute('UPDATE sessions SET ended=?, reason=? WHERE id=? AND ended IS NULL', (time.time(), reason, ident))
        self.event(ident, None, reason)

    def chat(self, visitor, ip, name, country, text):
        now = time.time()
        cursor = self.db.execute('INSERT INTO chat(at, visitor, ip, name, country, text) VALUES (?, ?, ?, ?, ?, ?)',
                                 (now, visitor, ip, name, country, text))
        self.db.commit()
        return {'id': cursor.lastrowid, 'at': now, 'visitor': visitor, 'ip': ip,
                'name': name, 'country': country, 'text': text}

    def chat_history(self, limit):
        rows = self.db.execute('SELECT * FROM chat WHERE hidden=0 ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
        return [dict(row) for row in reversed(rows)]

    def hide_chat(self, ident):
        changed = self.db.execute('UPDATE chat SET hidden=1 WHERE id=? AND hidden=0', (ident,)).rowcount
        self.db.commit()
        return changed > 0

    def logs(self, kind, page, query):
        search = '%' + query[:200] + '%'
        if kind == 'visits':
            sql = '''SELECT v.*, (SELECT count(*) FROM sessions s WHERE s.visit=v.id) AS sessions
                     FROM visits v WHERE v.ip LIKE ? OR v.visitor LIKE ? OR v.id LIKE ?'''
            order = 'at DESC'
        elif kind == 'matches':
            sql = '''SELECT m.*, sa.ip AS a_ip, sb.ip AS b_ip,
                     sa.visitor AS a_visitor, sb.visitor AS b_visitor
                     FROM matches m LEFT JOIN sessions sa ON sa.id=m.a LEFT JOIN sessions sb ON sb.id=m.b
                     WHERE sa.ip LIKE ? OR sb.ip LIKE ? OR m.id LIKE ?'''
            order = 'matched DESC'
        elif kind == 'diagnostics':
            sql = '''SELECT d.*, v.ip, v.visitor FROM diagnostics d JOIN visits v ON v.id=d.visit
                     WHERE v.ip LIKE ? OR d.visit LIKE ? OR v.visitor LIKE ?'''
            order = 'at DESC, id DESC'
        elif kind == 'events':
            sql = '''SELECT e.*, s.ip FROM events e LEFT JOIN sessions s ON s.id=e.actor
                     WHERE coalesce(s.ip, '') LIKE ? OR coalesce(e.match_id, '') LIKE ? OR coalesce(e.actor, '') LIKE ?'''
            order = 'at DESC, id DESC'
        elif kind == 'chat':
            sql = '''SELECT * FROM chat WHERE coalesce(ip, '') LIKE ? OR coalesce(visitor, '') LIKE ?
                     OR (name || ' ' || text) LIKE ?'''
            order = 'at DESC, id DESC'
        else:
            raise ValueError('Invalid log type')
        args = (search, search, search)
        total = self.db.execute('SELECT count(*) FROM (' + sql + ')', args).fetchone()[0]
        rows = self.db.execute(sql + ' ORDER BY ' + order + ' LIMIT 100 OFFSET ?', (*args, page * 100)).fetchall()
        rows = [dict(row) for row in rows]
        for row in rows:
            if kind == 'matches':
                row['a_location'] = self.cities.lookup(row['a_ip'])
                row['b_location'] = self.cities.lookup(row['b_ip'])
                row['a_country'] = self.countries.lookup(row['a_ip'])
                row['b_country'] = self.countries.lookup(row['b_ip'])
            else:
                row['location'] = self.cities.lookup(row['ip'])
                row['country'] = self.countries.lookup(row['ip'])
        return {'rows': rows, 'total': total, 'page': page, 'now': time.time()}

    def visitor_points(self):
        # One dot per browser, at its most recent resolvable city in retained history.
        # Publish only coordinate/count buckets, never identities or visit timestamps.
        addresses, seen, points = {}, set(), {}
        for row in self.db.execute('SELECT visitor, ip FROM visits ORDER BY at DESC, rowid DESC'):
            visitor = row['visitor']
            if not visitor or visitor in seen:
                continue
            ip = row['ip']
            if ip not in addresses:
                addresses[ip] = self.cities.lookup(ip)
            location = addresses[ip]
            lat, lon = location['latitude'], location['longitude']
            if lat is None or lon is None:
                continue
            seen.add(visitor)
            key = (lat, lon)
            points[key] = points.get(key, 0) + 1
        return [{'latitude': lat, 'longitude': lon, 'count': count}
                for (lat, lon), count in sorted(points.items())]

    def summary(self):
        return {key: self.db.execute(sql).fetchone()[0] for key, sql in {
            'visits': 'SELECT count(*) FROM visits',
            'visitors': 'SELECT count(DISTINCT visitor) FROM visits',
            'sessions': 'SELECT count(*) FROM sessions WHERE ended IS NULL',
            'matches': 'SELECT count(*) FROM matches WHERE ended IS NULL',
        }.items()}

    def close(self):
        self.countries.close()
        self.cities.close()
        self.db.close()

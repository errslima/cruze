from countries import Countries
from audit import Audit


def test_lookup_normalizes_and_handles_unknown(monkeypatch):
    class Reader:
        def get(self, ip):
            return {'country': {'iso_code': {'8.8.8.8': 'US', '2001:4860:4860::8888': 'US'}.get(ip)}}
        def close(self):
            pass
    monkeypatch.setattr('countries.maxminddb.open_database', lambda path: Reader())
    countries = Countries()
    for ip in ['8.8.8.8', '::ffff:8.8.8.8', '2001:4860:4860::8888']:
        assert countries.lookup(ip) == 'US'
    for ip in [None, '', 'invalid', '127.0.0.1', '192.168.1.1', '::1', '192.0.2.1', '1.1.1.1']:
        assert countries.lookup(ip) is None
    countries.close()


def test_missing_database(tmp_path):
    countries = Countries(str(tmp_path / 'missing.mmdb'))
    assert countries.lookup('8.8.8.8') is None
    countries.close()


def test_countries_include_historical_visits_matches_and_events(tmp_path, monkeypatch):
    path = str(tmp_path / 'audit.sqlite3')
    audit = Audit(path)
    audit.visit('visit', 'visitor', '8.8.8.8', 'test', '')
    audit.session('a', 'visit', 'visitor', '8.8.8.8', 'test')
    audit.session('b', '', 'other', '1.1.1.1', 'test')
    audit.match('match', 'a', 'b')
    audit.close()
    monkeypatch.setattr(Countries, 'lookup', lambda self, ip: {'8.8.8.8': 'US', '1.1.1.1': 'AU'}.get(ip))
    audit = Audit(path)
    assert audit.logs('visits', 0, '')['rows'][0]['country'] == 'US'
    match = audit.logs('matches', 0, '')['rows'][0]
    assert (match['a_country'], match['b_country']) == ('US', 'AU')
    events = audit.logs('events', 0, '')['rows']
    assert next(e for e in events if e['actor'] == 'a')['country'] == 'US'
    assert next(e for e in events if e['actor'] is None)['country'] is None
    audit.close()

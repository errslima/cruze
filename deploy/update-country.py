"""Download current DB-IP Country or City Lite release, validate, and replace atomically."""
import datetime
import gzip
import os
from pathlib import Path
import shutil
import sys
import tempfile
import urllib.request
import maxminddb

kind = 'city' if '--city' in sys.argv else 'country'
label = kind.title()
path = Path(os.getenv(f'CRUZE_{kind.upper()}_DB', f'data/{kind}.mmdb'))
month = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m')
url = f'https://download.db-ip.com/free/dbip-{kind}-lite-{month}.mmdb.gz'
path.parent.mkdir(parents=True, exist_ok=True)
# Keep an existing current-month database. Restart the application after updating.
if path.exists():
    with maxminddb.open_database(str(path)) as reader:
        built = datetime.datetime.fromtimestamp(reader.metadata().build_epoch, datetime.timezone.utc)
        if built.strftime('%Y-%m') == month:
            print(f'{label} database is current.')
            raise SystemExit(0)
try:
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
        temp = Path(output.name)
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Cruze/0.1 country-database-updater'}), timeout=60) as response, gzip.GzipFile(fileobj=response) as source:
            shutil.copyfileobj(source, output)
    with maxminddb.open_database(str(temp)) as reader:
        assert reader.get('8.8.8.8')['country']['iso_code']
    temp.chmod(0o644)
    temp.replace(path)
    print(f'Installed DB-IP {label} Lite {month}.')
finally:
    if 'temp' in locals():
        temp.unlink(missing_ok=True)

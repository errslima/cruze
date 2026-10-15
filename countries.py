"""Local IP geolocation; visitor IPs never leave the application."""
import ipaddress
import logging
import math
import os
import maxminddb


class Countries:
    def __init__(self, path=None):
        self.reader = None
        try:
            self.reader = maxminddb.open_database(path or os.getenv('CRUZE_COUNTRY_DB', 'data/country.mmdb'))
        except (OSError, ValueError, maxminddb.InvalidDatabaseError):
            logging.getLogger(__name__).warning('%s database unavailable; locations will be unknown', type(self).__name__)

    def record(self, value):
        try:
            address = ipaddress.ip_address(value)
            if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
                address = address.ipv4_mapped
            if not address.is_global or self.reader is None:
                return {}
            return self.reader.get(str(address)) or {}
        except (ValueError, TypeError, maxminddb.InvalidDatabaseError):
            return {}

    def lookup(self, value):
        code = self.record(value).get('country', {}).get('iso_code')
        return code if isinstance(code, str) and len(code) == 2 and code.isascii() and code.isalpha() and code.isupper() else None

    def close(self):
        if self.reader:
            self.reader.close()


class Cities(Countries):
    def __init__(self, path=None):
        super().__init__(path or os.getenv('CRUZE_CITY_DB', 'data/city.mmdb'))

    def lookup(self, value):
        record = self.record(value)
        city = record.get('city', {}).get('names', {}).get('en') or None
        subdivisions = record.get('subdivisions') or []
        region = subdivisions[0].get('names', {}).get('en') if subdivisions else None
        location = record.get('location') or {}
        lat, lon = location.get('latitude'), location.get('longitude')
        valid = (city and type(lat) in (int, float) and type(lon) in (int, float)
                 and math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180)
        return {'city': city, 'region': region, 'latitude': round(lat, 2) if valid else None,
                'longitude': round(lon, 2) if valid else None}

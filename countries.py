"""Local IP-country lookup; visitor IPs never leave the application."""
import ipaddress
import logging
import os
import maxminddb


class Countries:
    def __init__(self, path=None):
        self.reader = None
        try:
            self.reader = maxminddb.open_database(path or os.getenv('CRUZE_COUNTRY_DB', 'data/country.mmdb'))
        except (OSError, ValueError, maxminddb.InvalidDatabaseError):
            logging.getLogger(__name__).warning('Country database unavailable; countries will be unknown')

    def lookup(self, value):
        try:
            address = ipaddress.ip_address(value)
            if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
                address = address.ipv4_mapped
            if not address.is_global or self.reader is None:
                return None
            record = self.reader.get(str(address)) or {}
            code = record.get('country', {}).get('iso_code')
            return code if isinstance(code, str) and len(code) == 2 and code.isascii() and code.isalpha() and code.isupper() else None
        except (ValueError, TypeError, maxminddb.InvalidDatabaseError):
            return None

    def close(self):
        if self.reader:
            self.reader.close()

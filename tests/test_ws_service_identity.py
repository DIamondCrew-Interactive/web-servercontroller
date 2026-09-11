"""Compare our auth socket and native fixture with actual pinned Debian units."""
import configparser
import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import unittest

from ws_cookie import WS_ACCOUNT

ROOT = Path(__file__).resolve().parents[1]


class DebianServiceIdentity(unittest.TestCase):
    def test_http_and_https_instances_can_access_our_auth_socket(self):
        upstream = Path(os.environ.get('DCI_UPSTREAM', ROOT/'build/upstream'))
        package = upstream.parent/'debian/cockpit-ws.deb'
        if not package.is_file():
            self.skipTest('Fetch checksum-pinned Debian assets before this regression')
        lock = json.loads((ROOT/'tests/debian-packages.json').read_text())
        expected = next(p['sha256'] for p in lock['packages'] if p['package']=='cockpit-ws')
        raw = package.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), expected)
        self.assertTrue(raw.startswith(b'!<arch>\n'))
        offset = 8
        units = {}
        wanted = {'cockpit-wsinstance-http.service','cockpit-wsinstance-https@.service'}
        while offset < len(raw):
            header = raw[offset:offset+60]
            size = int(header[48:58])
            if header[:16].decode().strip().rstrip('/').startswith('data.tar'):
                with tarfile.open(fileobj=io.BytesIO(raw[offset+60:offset+60+size])) as archive:
                    for member in archive:
                        if member.isfile() and Path(member.name).name in wanted:
                            parser = configparser.ConfigParser(interpolation=None)
                            parser.read_string(archive.extractfile(member).read().decode())
                            units[Path(member.name).name] = parser['Service']
            offset += 60 + size + size % 2
        self.assertEqual(set(units), wanted)
        ours = configparser.ConfigParser(interpolation=None)
        ours.read(ROOT/'sso/systemd/dci-sso-auth.socket')
        self.assertEqual(int(ours['Socket']['SocketMode'],8),0o660)
        self.assertEqual(ours['Socket']['SocketUser'],'root')
        for name, service in units.items():
            with self.subTest(unit=name):
                self.assertEqual(ours['Socket']['SocketGroup'],service['Group'])
                self.assertEqual(WS_ACCOUNT,service['User'])


if __name__ == '__main__':
    unittest.main()

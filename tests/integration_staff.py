"""Real Staff/SC HTTP contract, with Discord and HTTPS transport mocked ONLY here.
Usage: python tests/integration_staff.py PATH_TO_STAFF_CHECKOUT (after npm ci there).
No PAM/session execution or production network requests.
"""
from contextlib import closing
import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from unittest.mock import patch
from urllib.parse import urlsplit, parse_qs, urlencode
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sso'))
import broker


def request(base, method, path, headers=None):
    with closing(http.client.HTTPConnection(urlsplit(base).netloc, timeout=10)) as client:
        client.request(method, path, headers=headers or {})
        response = client.getresponse()
        return response.status, response.getheaders(), response.read()


def cookie(headers, prefix):
    return next(v.split(';')[0] for k, v in headers if k.lower() == 'set-cookie' and v.startswith(prefix + '='))


def run(staff):
    process = subprocess.Popen(['node', '--import', 'tsx', 'tests/fixtures/sso-server.ts'], cwd=staff, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        try:
            fixture = json.loads(process.stdout.readline())
        except (ValueError, TypeError):
            raise RuntimeError('Staff fixture must emit JSON {origin, issuer, verification_keys}; old unsigned fixture is incompatible') from None
        staff_base = fixture['origin']
        verification_keys = fixture['verification_keys']
        issuer = fixture['issuer']
        if not staff_base.startswith('http://127.0.0.1:'):
            raise RuntimeError('Staff fixture did not start')
        real_opener = urllib.request.build_opener(broker.NoRedirect)
        class FixtureTransport:
            def open(self, req, timeout):
                assert req.full_url == issuer + '/sso/api/redeem'
                local = urllib.request.Request(staff_base + '/sso/api/redeem', data=req.data, headers=dict(req.header_items()))
                return real_opener.open(local, timeout=timeout)
        with tempfile.TemporaryDirectory() as directory, patch.object(broker.urllib.request, 'build_opener', return_value=FixtureTransport()):
            class Handler(broker.Handler):
                config = {'origin':'https://admin.example','staff_origin':issuer,'audience':'servercontroller','redeem_secret':'s' * 43,'verification_keys':verification_keys}
                store = broker.Store(Path(directory) / 'grants.sqlite3')
            broker.validate_config(Handler.config)
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            sc = f'http://127.0.0.1:{server.server_port}'
            try:
                status, headers, _ = request(sc, 'GET', '/auth/sso/start'); assert status == 302
                binding = cookie(headers, '__Host-dci-sso-state')
                start = urlsplit(dict(headers)['Location'])
                status, headers, _ = request(staff_base, 'GET', start.path + '?' + start.query); assert status == 302
                staff_binding = cookie(headers, 'dc_oauth')
                discord = urlsplit(dict(headers)['Location']); assert discord.netloc == 'discord.com'
                state = parse_qs(discord.query)['state'][0]
                status, headers, _ = request(staff_base, 'GET', '/auth/discord/callback?' + urlencode({'state':state, 'code':'test'}), {'Cookie':staff_binding}); assert status == 302
                staff_session = cookie(headers, 'dc_session')
                resume = dict(headers)['Location']
                status, headers, _ = request(staff_base, 'GET', resume, {'Cookie':staff_session}); assert status == 303
                callback = urlsplit(dict(headers)['Location']); assert callback.netloc == 'admin.example'
                status, headers, _ = request(sc, 'GET', callback.path + '?' + callback.query, {'Cookie':binding}); assert status == 303
                handle = cookie(headers, '__Host-dci-sso-ticket')
                status, _, body = request(sc, 'POST', '/auth/sso/redeem', {'Cookie':handle,'Origin':'https://admin.example','X-DCI-SSO':'1'}); assert status == 200
                ticket = json.loads(body)['ticket']
                assert Handler.store.consume(ticket, 'bearer') == '584274123622973440'
                assert Handler.store.consume(ticket, 'bearer') is None
                status, _, _ = request(sc, 'GET', callback.path + '?' + callback.query, {'Cookie':binding}); assert status == 400
                print('PASS: Staff OAuth session -> Staff signed issuance/redeem -> SC Ed25519 callback -> one-use local bearer, canonical ID preserved; callback replay refused. PAM not executed.')
            finally:
                server.shutdown(); server.server_close(); thread.join()
    finally:
        process.terminate()
        try: process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill(); process.communicate()


if __name__ == '__main__':
    run(Path(sys.argv[1]).resolve())

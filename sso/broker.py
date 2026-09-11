#!/usr/bin/env python3
"""Staff SSO relying party. No Discord OAuth code or Discord client credentials."""
import base64
import hashlib
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import re
import secrets
import socketserver
import stat
import time
import urllib.parse
import urllib.request

from grants import Store, TOKEN, SNOWFLAKE, hashed
from assertions import load_keys, strict_json, verify

CONFIG = Path('/etc/diamondcrew-servercontroller/sso.json')
SOCKET = '/run/dci-sso/http.sock'
DATABASE = Path('/var/lib/dci-sso/grants.sqlite3')


def challenge(verifier):
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')


def validate_config(config):
    if set(config) != {'origin', 'staff_origin', 'audience', 'redeem_secret', 'verification_keys'}:
        raise ValueError('Unexpected SSO configuration keys')
    for key in ['origin', 'staff_origin']:
        parsed = urllib.parse.urlsplit(config[key])
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            raise ValueError('HTTPS origin required')
    if config['origin'] == config['staff_origin'] or config['audience'] != 'servercontroller':
        raise ValueError('Invalid SSO audience/origin')
    if not re.fullmatch(r'[A-Za-z0-9_-]{43,128}', config['redeem_secret']):
        raise ValueError('Missing service credential')
    load_keys(config['verification_keys'])
    return config


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('SSO redemption redirects are forbidden')


def staff_identity(config, ticket, state, verifier, store):
    request = urllib.request.Request(config['staff_origin'] + '/sso/api/redeem',
        data=json.dumps({'ticket': ticket, 'audience': config['audience'], 'state': state, 'code_verifier': verifier}).encode(),
        headers={'Authorization': 'Bearer ' + config['redeem_secret'], 'Content-Type': 'application/json'})
    with urllib.request.build_opener(NoRedirect).open(request, timeout=10) as response:
        raw = response.read(8193)
        if len(raw) > 8192:
            raise ValueError('Oversized SSO response')
        envelope = strict_json(raw)
    if not isinstance(envelope, dict) or set(envelope) != {'assertion', 'token_type', 'expires_in'} or envelope.get('token_type') != 'DCI-SSO' or type(envelope.get('expires_in')) is not int or not 0 < envelope['expires_in'] <= 45:
        raise ValueError('Invalid signed SSO response')
    claims = verify(envelope['assertion'], config, state)
    store.accept_assertion(claims['iss'], claims['aud'], claims['jti'], claims['exp'])
    return claims['sub']


class Handler(BaseHTTPRequestHandler):
    config = None
    store = None
    server_version = 'DCI-SSO'

    def log_message(self, *args):
        pass  # Callback URLs contain tickets; never log them.

    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def cookie(self, name):
        try:
            values = SimpleCookie(self.headers.get('Cookie', ''))
            return values[name].value if name in values else ''
        except Exception:
            return ''

    def send(self, status, value=None, headers=()):
        payload = json.dumps(value).encode() if value is not None else b''
        self.send_response(status)
        for key, val in [('Content-Type', 'application/json; charset=utf-8'), ('Cache-Control', 'no-store'),
                         ('Referrer-Policy', 'no-referrer'), ('X-Content-Type-Options', 'nosniff'),
                         ('Content-Security-Policy', "default-src 'none'; frame-ancestors 'none'"),
                         ('Content-Length', str(len(payload))), *headers]:
            self.send_header(key, val)
        self.end_headers()
        self.wfile.write(payload)

    @staticmethod
    def cookie_header(name, value, ttl, same_site='Lax'):
        return ('Set-Cookie', f'{name}={value}; Path=/; Secure; HttpOnly; SameSite={same_site}; Max-Age={ttl}')

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path)
        try:
            if path.path == '/auth/sso/status':
                return self.send(200, {'enabled': True})
            if path.path == '/auth/sso/start':
                binding, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                state = self.store.issue('state', json.dumps({'binding': hashed(binding), 'verifier': verifier}), 600)
                query = urllib.parse.urlencode({'state': state, 'code_challenge': challenge(verifier)})
                return self.send(302, headers=[('Location', self.config['staff_origin'] + '/sso/servercontroller?' + query),
                    self.cookie_header('__Host-dci-sso-state', binding, 600), self.cookie_header('__Host-dci-sso-ticket', '', 0, 'Strict')])
            if path.path == '/auth/sso/callback':
                params = urllib.parse.parse_qs(path.query, keep_blank_values=True, max_num_fields=4)
                if any(len(values) != 1 for values in params.values()) or set(params) not in ({'ticket','state'}, {'error','state'}):
                    raise ValueError('Invalid callback parameters')
                state, binding = params.get('state', [''])[0], self.cookie('__Host-dci-sso-state')
                pending = self.store.consume(state, 'state')
                if not pending or not TOKEN.fullmatch(binding):
                    raise ValueError('Invalid browser binding')
                pending = json.loads(pending)
                if not secrets.compare_digest(pending['binding'], hashed(binding)):
                    raise ValueError('Invalid browser binding')
                if 'error' in params:
                    payload = json.dumps({'error': 'access_denied'})
                else:
                    ticket = params['ticket'][0]
                    if not TOKEN.fullmatch(ticket):
                        raise ValueError('Invalid ticket')
                    payload = json.dumps({'subject': staff_identity(self.config, ticket, state, pending['verifier'], self.store)})
                handle = self.store.issue('redeem', payload, 30)
                return self.send(303, headers=[('Location', '/'), self.cookie_header('__Host-dci-sso-state', '', 0),
                    self.cookie_header('__Host-dci-sso-ticket', handle, 30, 'Strict')])
            self.send(404)
        except Exception:
            self.send(400, {'error': 'SSO sign-in failed. Return to the login page and try again.'},
                [self.cookie_header('__Host-dci-sso-state', '', 0)])

    def do_POST(self):
        try:
            if self.path in ('/auth/sso/redeem', '/auth/sso/logout'):
                if self.headers.get('Origin') != self.config['origin'] or self.headers.get('X-DCI-SSO') != '1':
                    return self.send(403, {'error': 'forbidden'})
                handle = self.cookie('__Host-dci-sso-ticket')
                cleared = [self.cookie_header('__Host-dci-sso-ticket', '', 0, 'Strict')]
                if self.path.endswith('/logout'):
                    self.store.consume(handle, 'redeem')
                    return self.send(204, headers=cleared)
                if not handle:
                    return self.send(204)
                payload = self.store.consume(handle, 'redeem')
                if not payload:
                    return self.send(401, headers=cleared)
                payload = json.loads(payload)
                if 'error' in payload:
                    return self.send(403, {'error': 'access_denied'}, cleared)
                return self.send(200, {'ticket': self.store.issue('bearer', payload['subject'], 30)}, cleared)
            if self.path == '/internal/consume':
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 256:
                    return self.send(400)
                identity = self.store.consume(json.loads(self.rfile.read(size)).get('ticket', ''), 'bearer')
                return self.send(200, {'discord_id': identity}) if identity else self.send(401)
            self.send(404)
        except Exception:
            self.send(400, {'error': 'Invalid request'})


if __name__ == '__main__':
    if os.geteuid() == 0:
        raise SystemExit('SSO HTTP service must not run as root')
    directory = os.environ.get('CREDENTIALS_DIRECTORY')
    config_path = Path(directory) / 'sso.json' if directory else CONFIG
    Handler.config = validate_config(json.loads(config_path.read_text(encoding='utf-8')))
    Handler.store = Store(DATABASE)
    if os.path.lexists(SOCKET):
        previous = os.lstat(SOCKET)
        if not stat.S_ISSOCK(previous.st_mode) or previous.st_uid != os.geteuid():
            raise SystemExit('Unexpected runtime socket')
        os.unlink(SOCKET)
    with socketserver.UnixStreamServer(SOCKET, Handler) as server:
        os.chmod(SOCKET, 0o660)
        server.serve_forever()

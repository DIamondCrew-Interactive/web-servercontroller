#!/usr/bin/env python3
"""Discord authorization-code broker. Runs as dci-discord, never as root."""
import hashlib
from contextlib import closing
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler
import json
import os
from pathlib import Path
import re
import secrets
import socketserver
import sqlite3
import stat
import time
import urllib.parse
import urllib.request

CONFIG = Path('/etc/dci-discord/oauth.json')
DATABASE = Path('/var/lib/dci-discord/oauth.sqlite3')
SOCKET = '/run/dci-discord/http.sock'
TOKEN = re.compile(r'^[A-Za-z0-9_-]{43}$')
SNOWFLAKE = re.compile(r'^[0-9]{17,20}$')


def hashed(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Store:
    def __init__(self, path):
        self.path = path
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS grants (key TEXT PRIMARY KEY, kind TEXT, value TEXT, expires REAL)')

    def issue(self, kind, value, ttl):
        token = secrets.token_urlsafe(32)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DELETE FROM grants WHERE expires < ?', (time.time(),))
            if db.execute('SELECT count(*) FROM grants').fetchone()[0] >= 4096:
                raise ValueError('Too many pending logins')
            db.execute('INSERT INTO grants VALUES (?, ?, ?, ?)', (hashed(token), kind, value, time.time() + ttl))
        return token

    def consume(self, token, kind):
        if not TOKEN.fullmatch(token):
            return None
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT value, expires FROM grants WHERE key=? AND kind=?', (hashed(token), kind)).fetchone()
            db.execute('DELETE FROM grants WHERE key=? AND kind=?', (hashed(token), kind))
        return row[0] if row and row[1] > time.time() else None


def validate_config(config):
    origin = urllib.parse.urlsplit(config.get('origin', ''))
    if origin.scheme != 'https' or not origin.hostname or origin.path or origin.query or origin.fragment or origin.username or origin.password:
        raise ValueError('origin must be an HTTPS origin without path or credentials')
    if not SNOWFLAKE.fullmatch(config.get('client_id', '')) or not config.get('client_secret'):
        raise ValueError('Discord Client ID and Client Secret are required')
    return config


def discord_identity(config, code):
    form = urllib.parse.urlencode({'client_id': config['client_id'], 'client_secret': config['client_secret'],
                                  'grant_type': 'authorization_code', 'code': code,
                                  'redirect_uri': config['origin'] + '/discord/callback'}).encode()
    request = urllib.request.Request('https://discord.com/api/oauth2/token', data=form,
                                     headers={'Content-Type': 'application/x-www-form-urlencoded', 'User-Agent': 'DCI-ServerController'})
    with urllib.request.urlopen(request, timeout=15) as response:
        token = json.load(response)
    if 'identify' not in token.get('scope', '').split() or not token.get('access_token'):
        raise ValueError('Required OAuth scope missing')
    request = urllib.request.Request('https://discord.com/api/v10/users/@me', headers={
        'Authorization': 'Bearer ' + token['access_token'], 'User-Agent': 'DCI-ServerController'})
    with urllib.request.urlopen(request, timeout=15) as response:
        identity = json.load(response)
    if not SNOWFLAKE.fullmatch(identity.get('id', '')):
        raise ValueError('Invalid Discord identity')
    # Access/refresh tokens are not persisted, returned to browser or logged.
    return identity['id']


class Handler(BaseHTTPRequestHandler):
    config = None
    store = None
    server_version = 'DCI-OAuth'

    def log_message(self, *args):
        pass  # Query strings contain OAuth codes; never use default access logging.

    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def cookie(self, name):
        try:
            cookie = SimpleCookie(self.headers.get('Cookie', ''))
            return cookie[name].value if name in cookie else ''
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

    def cookie_header(self, name, value, ttl, same_site='Lax'):
        return ('Set-Cookie', f'{name}={value}; Path=/; Secure; HttpOnly; SameSite={same_site}; Max-Age={ttl}')

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path)
        try:
            if path.path == '/discord/status':
                return self.send(200, {'enabled': True})
            if path.path == '/discord/start':
                binding = secrets.token_urlsafe(32)
                state = self.store.issue('state', hashed(binding), 300)
                query = urllib.parse.urlencode({'client_id': self.config['client_id'], 'response_type': 'code',
                                               'scope': 'identify', 'state': state, 'prompt': 'consent',
                                               'redirect_uri': self.config['origin'] + '/discord/callback'})
                return self.send(302, headers=[('Location', 'https://discord.com/oauth2/authorize?' + query),
                                               self.cookie_header('__Host-dci-oauth', binding, 300)])
            if path.path == '/discord/callback':
                params = urllib.parse.parse_qs(path.query)
                if any(len(values) != 1 for values in params.values()):
                    raise ValueError('Duplicate parameters')
                state = params.get('state', [''])[0]
                binding = self.cookie('__Host-dci-oauth')
                expected = self.store.consume(state, 'state')
                if not expected or not TOKEN.fullmatch(binding) or not secrets.compare_digest(expected, hashed(binding)):
                    raise ValueError('OAuth state mismatch')
                code = params.get('code', [''])[0]
                if not code or len(code) > 2048 or 'error' in params:
                    raise ValueError('OAuth not authorized')
                identity = discord_identity(self.config, code)
                # Browser cookie contains a separate redeem handle; bearer is issued on same-origin POST.
                handle = self.store.issue('redeem', identity, 60)
                return self.send(303, headers=[('Location', '/'), self.cookie_header('__Host-dci-oauth', '', 0),
                                               self.cookie_header('__Host-dci-ticket', handle, 60, 'Strict')])
            self.send(404, {'error': 'Not found'})
        except Exception:
            self.send(400, {'error': 'Discord login failed. Return to the login page and try again.'},
                      [self.cookie_header('__Host-dci-oauth', '', 0)])

    def do_POST(self):
        try:
            if self.path == '/discord/redeem':
                if self.headers.get('Origin') != self.config['origin'] or self.headers.get('X-DCI-OAuth') != '1':
                    return self.send(403, {'error': 'Forbidden'})
                handle = self.cookie('__Host-dci-ticket')
                if not handle:
                    return self.send(204)
                identity = self.store.consume(handle, 'redeem')
                cleared = [self.cookie_header('__Host-dci-ticket', '', 0, 'Strict')]
                if not identity:
                    return self.send(401, {'error': 'Expired login'}, cleared)
                return self.send(200, {'ticket': self.store.issue('bearer', identity, 30)}, cleared)
            if self.path == '/internal/consume':
                # Not exposed by the /discord/ reverse-proxy location. Ticket is still required.
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
        raise SystemExit('OAuth HTTP service must not run as root')
    Handler.config = validate_config(json.loads(CONFIG.read_text(encoding='utf-8')))
    Handler.store = Store(DATABASE)
    if os.path.lexists(SOCKET):
        previous = os.lstat(SOCKET)
        if not stat.S_ISSOCK(previous.st_mode) or previous.st_uid != os.geteuid():
            raise SystemExit('Unexpected runtime socket')
        os.unlink(SOCKET)
    with socketserver.UnixStreamServer(SOCKET, Handler) as server:
        os.chmod(SOCKET, 0o660)
        server.serve_forever()

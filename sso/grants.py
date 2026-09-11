"""Atomic, purpose-scoped, single-use local grants. Never stores raw credentials."""
from contextlib import closing
import hashlib
import re
import secrets
import sqlite3
import time

TOKEN = re.compile(r'^[A-Za-z0-9_-]{43}$')
SNOWFLAKE = re.compile(r'^[0-9]{17,20}$')


def hashed(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Store:
    def __init__(self, path):
        self.path = path
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS grants (key TEXT PRIMARY KEY, kind TEXT, value TEXT, expires REAL)')
            db.execute('CREATE TABLE IF NOT EXISTS used_assertions (key TEXT PRIMARY KEY, expires REAL NOT NULL)')

    def accept_assertion(self, issuer, audience, jti, expires):
        key = hashed(issuer + '\0' + audience + '\0' + jti)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            now = time.time()
            if expires <= now:
                raise ValueError('Assertion expired before acceptance')
            db.execute('DELETE FROM used_assertions WHERE expires <= ?', (now,))
            if db.execute('SELECT count(*) FROM used_assertions').fetchone()[0] >= 10000:
                raise ValueError('Assertion replay cache full')
            try:
                db.execute('INSERT INTO used_assertions VALUES (?, ?)', (key, expires + 5))
            except sqlite3.IntegrityError:
                raise ValueError('Staff assertion already used') from None

    def issue(self, kind, value, ttl):
        token = secrets.token_urlsafe(32)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DELETE FROM grants WHERE expires <= ?', (time.time(),))
            if db.execute('SELECT count(*) FROM grants').fetchone()[0] >= 4096:
                raise ValueError('Too many pending logins')
            db.execute('INSERT INTO grants VALUES (?, ?, ?, ?)', (hashed(token), kind, value, time.time() + ttl))
        return token

    def consume(self, token, kind):
        if not isinstance(token, str) or not TOKEN.fullmatch(token):
            return None
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT value, expires FROM grants WHERE key=? AND kind=?', (hashed(token), kind)).fetchone()
            db.execute('DELETE FROM grants WHERE key=? AND kind=?', (hashed(token), kind))
        return row[0] if row and row[1] > time.time() else None

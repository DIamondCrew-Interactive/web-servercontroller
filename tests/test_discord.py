import http.client
from contextlib import closing
from http.server import ThreadingHTTPServer
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'discord'))
import oauth
import accounts
import auth


class DiscordFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = oauth.Store(Path(self.temp.name) / 'grants.sqlite3')
        class TestHandler(oauth.Handler):
            pass
        TestHandler.config = {'origin': 'https://admin.example', 'client_id': '12345678901234567', 'client_secret': 'test-only'}
        TestHandler.store = self.store
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), TestHandler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.identity = patch.object(oauth, 'discord_identity', return_value='12345678901234567').start()
        self.addCleanup(patch.stopall)

    def request(self, method, path, body=None, headers=None):
        with closing(http.client.HTTPConnection(*self.server.server_address)) as client:
            client.request(method, path, body=body, headers=headers or {})
            response = client.getresponse()
            return response.status, response.getheaders(), response.read()

    def start(self):
        status, headers, _ = self.request('GET', '/discord/start')
        self.assertEqual(status, 302)
        values = dict(headers)
        query = parse_qs(urlsplit(values['Location']).query)
        self.assertEqual(query['scope'], ['identify'])
        self.assertEqual(query['response_type'], ['code'])
        self.assertIn('Secure; HttpOnly; SameSite=Lax', values['Set-Cookie'])
        return query['state'][0], values['Set-Cookie'].split(';', 1)[0]

    def callback(self):
        state, cookie = self.start()
        return self.request('GET', '/discord/callback?' + urlencode({'state': state, 'code': 'test-code'}), headers={'Cookie': cookie})

    def test_full_code_redeem_and_one_use_bearer_flow(self):
        status, headers, _ = self.callback()
        self.assertEqual(status, 303)
        self.identity.assert_called_once()
        cookie = next(value for key, value in headers if key == 'Set-Cookie' and value.startswith('__Host-dci-ticket='))
        headers = {'Cookie': cookie.split(';', 1)[0], 'Origin': 'https://admin.example', 'X-DCI-OAuth': '1'}
        status, _, body = self.request('POST', '/discord/redeem', headers=headers)
        self.assertEqual(status, 200)
        ticket = json.loads(body)['ticket']
        self.assertRegex(ticket, oauth.TOKEN)
        self.assertEqual(self.request('POST', '/discord/redeem', headers=headers)[0], 401)
        body = json.dumps({'ticket': ticket})
        status, _, response = self.request('POST', '/internal/consume', body)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(response), {'discord_id': '12345678901234567'})
        self.assertEqual(self.request('POST', '/internal/consume', body)[0], 401)

    def test_callback_cookie_binding_and_state_replay(self):
        state, cookie = self.start()
        path = '/discord/callback?' + urlencode({'state': state, 'code': 'test-code'})
        self.assertEqual(self.request('GET', path)[0], 400)
        self.assertEqual(self.request('GET', path, headers={'Cookie': cookie})[0], 400)
        self.identity.assert_not_called()

    def test_cross_origin_redeem_refused_without_consuming_cookie(self):
        handle = self.store.issue('redeem', '12345678901234567', 60)
        headers = {'Cookie': '__Host-dci-ticket=' + handle, 'Origin': 'https://attacker.example', 'X-DCI-OAuth': '1'}
        self.assertEqual(self.request('POST', '/discord/redeem', headers=headers)[0], 403)
        self.assertEqual(self.store.consume(handle, 'redeem'), '12345678901234567')

    def test_duplicate_callback_parameters_refused(self):
        state, cookie = self.start()
        self.assertEqual(self.request('GET', '/discord/callback?state=' + state + '&state=another&code=x', headers={'Cookie': cookie})[0], 400)
        self.identity.assert_not_called()

    def test_expired_and_wrong_purpose_tickets_fail(self):
        ticket = self.store.issue('state', 'test', -1)
        self.assertIsNone(self.store.consume(ticket, 'state'))
        ticket = self.store.issue('redeem', 'test', 60)
        self.assertIsNone(self.store.consume(ticket, 'bearer'))
        self.assertEqual(self.store.consume(ticket, 'redeem'), 'test')

    def test_no_ticket_is_normal_password_login(self):
        self.assertEqual(self.request('POST', '/discord/redeem', headers={'Origin': 'https://admin.example', 'X-DCI-OAuth': '1'})[0], 204)

    def test_status_and_no_cache_headers(self):
        status, headers, body = self.request('GET', '/discord/status')
        self.assertEqual(status, 200)
        self.assertEqual(dict(headers)['Cache-Control'], 'no-store')
        self.assertEqual(json.loads(body), {'enabled': True})


class IdentityAndProtocolTests(unittest.TestCase):
    def test_https_origin_and_credentials_required(self):
        for origin in ['http://example.com', 'https://example.com/path', 'https://user@example.com', 'https://example.com?x=1']:
            with self.assertRaises(ValueError):
                oauth.validate_config({'origin': origin, 'client_id': '12345678901234567', 'client_secret': 'test'})
        with self.assertRaises(ValueError):
            oauth.validate_config({'origin': 'https://example.com', 'client_id': '', 'client_secret': ''})

    def test_system_or_nologin_accounts_cannot_be_linked(self):
        for uid, shell in [(0, '/bin/bash'), (999, '/bin/bash'), (65534, '/bin/bash'), (1000, '/usr/sbin/nologin')]:
            self.assertFalse(accounts.eligible(types.SimpleNamespace(pw_uid=uid, pw_shell=shell)))
        self.assertTrue(accounts.eligible(types.SimpleNamespace(pw_uid=1000, pw_shell='/bin/bash')))

    def test_deleted_recreated_uid_is_not_same_identity(self):
        fake_pwd = types.SimpleNamespace(getpwnam=lambda _: types.SimpleNamespace(pw_uid=1002, pw_shell='/bin/bash'))
        with patch.dict(sys.modules, {'pwd': fake_pwd}), patch.object(accounts, 'read_mapping', return_value={'12345678901234567': {'username': 'example', 'uid': 1001}}):
            with self.assertRaisesRegex(ValueError, 'changed'):
                accounts.linked_user('12345678901234567')
            with self.assertRaisesRegex(ValueError, 'not linked'):
                accounts.linked_user('99999999999999999')

    def test_cockpit_control_frame_roundtrip(self):
        output = types.SimpleNamespace(buffer=io.BytesIO())
        message = {'command': 'authorize', 'cookie': 'example', 'challenge': '*'}
        with patch.object(sys, 'stdout', output):
            auth.send_frame(message)
        with patch.object(sys, 'stdin', types.SimpleNamespace(buffer=io.BytesIO(output.buffer.getvalue()))):
            self.assertEqual(auth.read_frame(), message)

    def test_oversized_truncated_and_noncontrol_frames_refused(self):
        for payload in [b'999999\n', b'20\n\n{}', b'3\nx{}', b'invalid\n']:
            with patch.object(sys, 'stdin', types.SimpleNamespace(buffer=io.BytesIO(payload))), self.assertRaises(ValueError):
                auth.read_frame()


if __name__ == '__main__':
    unittest.main()

import http.client
from contextlib import closing
from http.server import ThreadingHTTPServer
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import threading
import types
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sso'))
import broker as oauth
import accounts
import auth
import signed_fixtures as signed


class DiscordFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = oauth.Store(Path(self.temp.name) / 'grants.sqlite3')
        class TestHandler(oauth.Handler):
            pass
        TestHandler.config = {'origin': 'https://admin.example', 'staff_origin': 'https://staff.example', 'audience': 'servercontroller', 'redeem_secret': 's' * 43}
        TestHandler.store = self.store
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), TestHandler)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.identity = patch.object(oauth, 'staff_identity', return_value='12345678901234567').start()
        self.addCleanup(patch.stopall)

    def request(self, method, path, body=None, headers=None):
        with closing(http.client.HTTPConnection(*self.server.server_address)) as client:
            client.request(method, path, body=body, headers=headers or {})
            response = client.getresponse()
            return response.status, response.getheaders(), response.read()

    def start(self):
        status, headers, _ = self.request('GET', '/auth/sso/start')
        self.assertEqual(status, 302)
        values = dict(headers)
        query = parse_qs(urlsplit(values['Location']).query)
        self.assertEqual(urlsplit(values['Location']).netloc, 'staff.example')
        self.assertRegex(query['code_challenge'][0], oauth.TOKEN)
        state_cookie = next(value for key, value in headers if key == 'Set-Cookie' and value.startswith('__Host-dci-sso-state='))
        self.assertIn('Secure; HttpOnly; SameSite=Lax', state_cookie)
        return query['state'][0], state_cookie.split(';', 1)[0]

    def callback(self):
        state, cookie = self.start()
        return self.request('GET', '/auth/sso/callback?' + urlencode({'state': state, 'ticket': 't' * 43}), headers={'Cookie': cookie})

    def test_full_code_redeem_and_one_use_bearer_flow(self):
        status, headers, _ = self.callback()
        self.assertEqual(status, 303)
        self.identity.assert_called_once()
        cookie = next(value for key, value in headers if key == 'Set-Cookie' and value.startswith('__Host-dci-sso-ticket='))
        headers = {'Cookie': cookie.split(';', 1)[0], 'Origin': 'https://admin.example', 'X-DCI-SSO': '1'}
        status, _, body = self.request('POST', '/auth/sso/redeem', headers=headers)
        self.assertEqual(status, 200)
        ticket = json.loads(body)['ticket']
        self.assertRegex(ticket, oauth.TOKEN)
        self.assertEqual(self.request('POST', '/auth/sso/redeem', headers=headers)[0], 401)
        body = json.dumps({'ticket': ticket})
        status, _, response = self.request('POST', '/internal/consume', body)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(response), {'discord_id': '12345678901234567'})
        self.assertEqual(self.request('POST', '/internal/consume', body)[0], 401)

    def test_callback_cookie_binding_and_state_replay(self):
        state, cookie = self.start()
        path = '/auth/sso/callback?' + urlencode({'state': state, 'ticket': 't' * 43})
        self.assertEqual(self.request('GET', path)[0], 400)
        self.assertEqual(self.request('GET', path, headers={'Cookie': cookie})[0], 400)
        self.identity.assert_not_called()

    def test_cross_origin_redeem_refused_without_consuming_cookie(self):
        handle = self.store.issue('redeem', json.dumps({'subject': '12345678901234567'}), 60)
        headers = {'Cookie': '__Host-dci-sso-ticket=' + handle, 'Origin': 'https://attacker.example', 'X-DCI-SSO': '1'}
        self.assertEqual(self.request('POST', '/auth/sso/redeem', headers=headers)[0], 403)
        self.assertEqual(json.loads(self.store.consume(handle, 'redeem'))['subject'], '12345678901234567')

    def test_duplicate_callback_parameters_refused(self):
        state, cookie = self.start()
        self.assertEqual(self.request('GET', '/auth/sso/callback?state=' + state + '&state=another&code=x', headers={'Cookie': cookie})[0], 400)
        self.identity.assert_not_called()

    def test_expired_and_wrong_purpose_tickets_fail(self):
        ticket = self.store.issue('state', 'test', -1)
        self.assertIsNone(self.store.consume(ticket, 'state'))
        ticket = self.store.issue('redeem', 'test', 60)
        self.assertIsNone(self.store.consume(ticket, 'bearer'))
        self.assertEqual(self.store.consume(ticket, 'redeem'), 'test')

    def test_no_ticket_is_normal_password_login(self):
        self.assertEqual(self.request('POST', '/auth/sso/redeem', headers={'Origin': 'https://admin.example', 'X-DCI-SSO': '1'})[0], 204)

    def test_status_and_no_cache_headers(self):
        status, headers, body = self.request('GET', '/auth/sso/status')
        self.assertEqual(status, 200)
        self.assertEqual(dict(headers)['Cache-Control'], 'no-store')
        self.assertEqual(json.loads(body), {'enabled': True})


class IdentityAndProtocolTests(unittest.TestCase):
    def test_https_origin_and_credentials_required(self):
        valid = signed.config(signed.keys()[1])
        self.assertEqual(oauth.validate_config(valid), valid)
        for origin in ['http://example.com', 'https://example.com/path', 'https://user@example.com', 'https://example.com?x=1']:
            with self.assertRaises(ValueError):
                oauth.validate_config({**valid, 'origin': origin})
        with self.assertRaises(ValueError):
            oauth.validate_config({**valid, 'redeem_secret': ''})
        with self.assertRaises(ValueError):
            oauth.validate_config({**valid, 'audience': 'proxymanager'})
        with self.assertRaises(ValueError):
            oauth.validate_config({**valid, 'DISCORD_CLIENT_SECRET': 'forbidden'})

    def test_staff_response_claim_validation_and_no_redirects(self):
        private, public = signed.keys()
        config = signed.config(public)
        with tempfile.TemporaryDirectory() as directory:
            store = oauth.Store(Path(directory) / 'grants.sqlite3')
            value = signed.claims()
            with patch.object(oauth.urllib.request, 'build_opener') as factory:
                factory.return_value.open.return_value.__enter__.return_value.read.return_value = json.dumps(signed.envelope(private, value)).encode()
                self.assertEqual(oauth.staff_identity(config, 'a' * 43, 't' * 43, 'v' * 43, store), value['sub'])
                request = factory.return_value.open.call_args.args[0]
                self.assertEqual(request.full_url, 'https://staff.example/sso/api/redeem')
                self.assertEqual(request.get_header('Authorization'), 'Bearer ' + 's' * 43)
                self.assertEqual(json.loads(request.data)['audience'], 'servercontroller')
                with self.assertRaisesRegex(ValueError, 'already used'):
                    oauth.staff_identity(config, 'a' * 43, 't' * 43, 'v' * 43, store)
                factory.return_value.open.return_value.__enter__.return_value.read.return_value = json.dumps(value).encode()
                with self.assertRaisesRegex(ValueError, 'signed SSO response'):
                    oauth.staff_identity(config, 'a' * 43, 't' * 43, 'v' * 43, store)
        with self.assertRaises(ValueError):
            oauth.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.example')

    def test_servercontroller_runtime_has_no_discord_oauth_client(self):
        root = Path(__file__).resolve().parents[1]
        for folder in ['sso', 'src']:
            for source in (root / folder).rglob('*'):
                if source.suffix in ['.py', '.js', '.json', '.sh', '.service']:
                    text = source.read_text(encoding='utf-8')
                    self.assertNotIn('discord.com/api', text, str(source))
                    self.assertNotIn('DISCORD_CLIENT_SECRET', text, str(source))

    def test_concurrent_local_redemption_is_single_use(self):
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as directory:
            store = oauth.Store(Path(directory) / 'grants.sqlite3')
            token = store.issue('bearer', '584274123622973440', 30)
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lambda _: store.consume(token, 'bearer'), range(8)))
            self.assertEqual(results.count('584274123622973440'), 1)
            self.assertEqual(results.count(None), 7)

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

import concurrent.futures
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sso'))
import assertions
import broker
from grants import Store
import signed_fixtures as signed


class SignedAssertions(unittest.TestCase):
    def setUp(self):
        self.private, public = signed.keys()
        self.config = signed.config(public)
        self.claims = signed.claims(iat=1000, exp=1045)

    def verify(self, changes=None, header=None, **kwargs):
        return assertions.verify(signed.sign(self.private, {**self.claims, **(changes or {})}, header, **kwargs), self.config, 't' * 43, now=1000)

    def test_valid_and_clock_boundaries(self):
        self.assertEqual(self.verify(), self.claims)
        self.verify({'iat':1005, 'exp':1050})
        for changes in [{'iat':1006, 'exp':1051}, {'iat':955, 'exp':1000}, {'exp':1046}, {'exp':1000}, {'iat':True}, {'exp':1045.0}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.verify(changes)

    def test_identity_audience_state_issuer_and_jti(self):
        for changes in [{'aud':'proxymanager'}, {'aud':['servercontroller']}, {'iss':'https://evil.example'}, {'sub':584274123622973440}, {'sub':'skopy'}, {'state':'u'*43}, {'jti':'j'*43}, {'jti':self.claims['jti'].upper()}, {'extra':'claim'}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.verify(changes)

    def test_header_algorithm_and_key_source_are_fixed(self):
        base = {'alg':'EdDSA', 'typ':'JWT', 'kid':'test-key'}
        for change in [{'alg':'none'}, {'alg':'HS256'}, {'typ':'other'}, {'kid':'unknown'}, {'jku':'https://evil.example/key'}, {'jwk':{}}, {'crit':[]}]:
            with self.subTest(change=change), self.assertRaises(ValueError): self.verify(header={**base, **change})
        with self.assertRaises(ValueError): self.verify(header={'alg':'EdDSA','typ':'JWT'})

    def test_wrong_key_tampering_and_encoding(self):
        other, _ = signed.keys()
        token = signed.sign(other, self.claims)
        with self.assertRaises(ValueError): assertions.verify(token, self.config, 't'*43, now=1000)
        valid = signed.sign(self.private, self.claims)
        for invalid in [valid+'=', valid[:-1], 'a.b.c', valid.replace(valid.split('.')[1], signed.b64(b'{}')), '', 'x'*4097]:
            with self.subTest(invalid=invalid[:30]), self.assertRaises(ValueError): assertions.verify(invalid, self.config, 't'*43, now=1000)

    def test_duplicate_json_and_nonfinite_numbers(self):
        raw = json.dumps(self.claims)[:-1] + ',"aud":"servercontroller"}'
        with self.assertRaises(ValueError): self.verify(raw_claims=raw.encode())
        with self.assertRaises(ValueError): assertions.strict_json('{"exp":NaN}')
        with self.assertRaises(ValueError): assertions.load_keys({})

    def test_durable_concurrent_replay_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'db'
            def accept(_):
                try:
                    Store(path).accept_assertion('https://staff.example','servercontroller', self.claims['jti'], 9999999999)
                    return True
                except ValueError:
                    return False
            Store(path)
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                self.assertEqual(sum(pool.map(accept, range(8))), 1)
            self.assertFalse(accept(9))

    def test_invalid_signature_never_enters_replay_cache(self):
        other, _ = signed.keys()
        claims = signed.claims()
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory)/'db')
            with patch.object(broker.urllib.request, 'build_opener') as factory:
                response = factory.return_value.open.return_value.__enter__.return_value
                response.read.return_value = json.dumps(signed.envelope(other, claims)).encode()
                with self.assertRaises(ValueError): broker.staff_identity(self.config, 'a'*43, 't'*43, 'v'*43, store)
                response.read.return_value = json.dumps(signed.envelope(self.private, claims)).encode()
                self.assertEqual(broker.staff_identity(self.config, 'a'*43, 't'*43, 'v'*43, store), claims['sub'])


if __name__ == '__main__':
    unittest.main()

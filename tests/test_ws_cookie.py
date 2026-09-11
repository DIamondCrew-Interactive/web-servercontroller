import json
import unittest
from ws_cookie import login_payload, response_shape


class LoginSchema(unittest.TestCase):
    def test_287_schema_without_optional_login_data_or_user(self):
        value = {'csrf-token':'test-only-session-proof'}
        self.assertEqual(login_payload(200,json.dumps(value)),value)

    def test_optional_login_data(self):
        value = {'csrf-token':'test-only-session-proof','login-data':{'user':'skopy'}}
        self.assertEqual(login_payload(200,json.dumps(value)),value)

    def test_invalid_shape_or_status_and_diagnostics_do_not_echo_credentials(self):
        for status,value in [(401,{'csrf-token':'test-only-session-proof'}),(200,{'user':'skopy'}),(200,{'csrf-token':None}),(200,[])]:
            with self.assertRaises(ValueError) as result: login_payload(status,json.dumps(value))
            self.assertNotIn('test-only-session-proof',str(result.exception))
        diagnostic=response_shape({'csrf-token':'hidden-value','login-data':{'user':'skopy','token':'another-hidden'}})
        self.assertEqual(diagnostic,{'keys':['csrf-token','login-data'],'login_data_keys':['token','user']})


if __name__ == '__main__': unittest.main()

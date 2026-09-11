import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from ws_cookie import login_payload, response_shape, prepare_config, WS_ACCOUNT


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


class FixturePermissions(unittest.TestCase):
    def test_config_applies_explicit_public_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(os, 'chmod', wraps=os.chmod) as chmod:
                config = prepare_config(root, root/'auth.sock')
            applied = {(call.args[0], call.args[1]) for call in chmod.call_args_list}
            self.assertIn((root/'ws-config', 0o755), applied)
            self.assertIn((root/'ws-config'/'cockpit', 0o755), applied)
            self.assertIn((config, 0o644), applied)
            self.assertIn('UnixPath = '+str(root/'auth.sock'), config.read_text())

    @unittest.skipUnless(os.name=='posix', 'requires actual POSIX umask semantics')
    def test_umask077_config_readable_by_real_ws_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); root.chmod(0o755)
            previous = os.umask(0o077)
            try:
                config = prepare_config(root, root/'auth.sock')
                self.assertEqual((root/'ws-config').stat().st_mode & 0o777,0o755)
                self.assertEqual(config.parent.stat().st_mode & 0o777,0o755)
                self.assertEqual(config.stat().st_mode & 0o777,0o644)
                if os.geteuid()==0:
                    import pwd
                    try:
                        reader = pwd.getpwnam(WS_ACCOUNT)
                    except KeyError:
                        self.skipTest('Native Cockpit wsinstance account is not installed')
                    pid = os.fork()
                    if pid==0:
                        try:
                            os.setgroups([])
                            os.setgid(reader.pw_gid)
                            os.setuid(reader.pw_uid)
                            config.read_text()
                        except BaseException:
                            os._exit(1)
                        os._exit(0)
                    _, status = os.waitpid(pid,0)
                    self.assertEqual(os.waitstatus_to_exitcode(status),0)
            finally:
                os.umask(previous)


if __name__ == '__main__': unittest.main()

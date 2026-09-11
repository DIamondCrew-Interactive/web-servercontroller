import ctypes
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'sso'))
import accounts
import auth
import cli


class MappingCli(unittest.TestCase):
    def test_command_dispatch(self):
        cases = [
            (['sso','link','skopy','584274123622973440'], ['link','--user','skopy','--discord-id','584274123622973440']),
            (['sso','unlink','584274123622973440'], ['unlink','--discord-id','584274123622973440']),
            (['sso','list'], ['list']),
            (['sso','show','skopy'], ['show','--user','skopy']),
            (['sso','show','584274123622973440'], ['show','--discord-id','584274123622973440']),
        ]
        for args, expected in cases:
            with self.subTest(args=args), patch.object(sys,'argv',['dci-servercontroller',*args]), patch.object(cli.os,'geteuid',return_value=0,create=True), patch.object(accounts,'read_mapping',return_value={'584274123622973440':{'username':'skopy','uid':1000}}), patch.object(accounts,'main') as target:
                cli.main()
                target.assert_called_once()
                self.assertEqual(sys.argv[1:], expected)

    def test_nonroot_rejected_before_mapping(self):
        with patch.object(cli.os,'geteuid',return_value=1000,create=True), patch.object(accounts,'main') as target:
            with self.assertRaises(SystemExit): cli.main()
            target.assert_not_called()

    def test_show_returns_only_requested_mapping(self):
        fake_fcntl = types.SimpleNamespace(flock=lambda *args:None, LOCK_EX=2)
        records = {'584274123622973440':{'username':'skopy','uid':1000},'317014531144679424':{'username':'other','uid':1001}}
        with tempfile.TemporaryDirectory() as directory, patch.dict(sys.modules,{'fcntl':fake_fcntl,'pwd':types.SimpleNamespace()}), patch.object(accounts,'MAPPING',Path(directory)/'mapping.json'), patch.object(accounts.os,'geteuid',return_value=0,create=True), patch.object(accounts,'read_mapping',return_value=records), patch.object(sys,'argv',['accounts','show','--user','skopy']), patch.object(sys,'stdout',new_callable=io.StringIO) as output:
            accounts.main()
            self.assertEqual(json.loads(output.getvalue()), {'links':{'584274123622973440':records['584274123622973440']}})


class PamCleanup(unittest.TestCase):
    def test_cleanup_runs_all_phases_even_if_close_fails(self):
        pam = auth.PAM.__new__(auth.PAM)
        pam.opened = pam.credentials = True
        pam.handle = ctypes.c_void_p(1)
        pam.lib = types.SimpleNamespace(pam_close_session=Mock(return_value=1),pam_setcred=Mock(return_value=0),pam_end=Mock(return_value=0))
        with self.assertRaisesRegex(ValueError,'cleanup failed'): pam.close()
        pam.lib.pam_setcred.assert_called_once()
        pam.lib.pam_end.assert_called_once()
        pam.close()
        pam.lib.pam_close_session.assert_called_once()


if __name__ == '__main__':
    unittest.main()

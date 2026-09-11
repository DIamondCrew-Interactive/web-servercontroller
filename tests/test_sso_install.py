"""Real temporary files, mocked Debian commands. Does not prove native systemd/PAM."""
from contextlib import ExitStack
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import signed_fixtures as signed

SOURCE = Path(__file__).resolve().parents[1] / 'sso'
sys.path.insert(0, str(SOURCE))


class SsoInstallTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        fake_pwd = types.SimpleNamespace(getpwnam=lambda _: types.SimpleNamespace(pw_uid=123, pw_shell='/usr/sbin/nologin'))
        fake_grp = types.SimpleNamespace(getgrnam=lambda _: types.SimpleNamespace(gr_gid=123))
        with patch.dict(sys.modules, {'pwd':fake_pwd, 'grp':fake_grp}):
            spec = importlib.util.spec_from_file_location('dci_sso_install_test', SOURCE / 'install.py')
            self.m = importlib.util.module_from_spec(spec); spec.loader.exec_module(self.m)
        m = self.m
        for key, relative in {'TARGET':'lib/dci-sso', 'CONF':'etc/cockpit.conf', 'ROOT_CONFIG':'etc/sso.json', 'OS_RELEASE':'os-release', 'SYSTEMD':'units', 'CLI':'bin/dci-servercontroller', 'STATE':'state/install.json', 'LEGACY':'state/old.json'}.items():
            path = self.root / relative; path.parent.mkdir(parents=True, exist_ok=True)
            setattr(m, key, path)
        m.SYSTEMD.mkdir()
        m.OS_RELEASE.write_text('ID=debian\nVERSION_ID="12"\n')
        self.original = '[WebService]\nOrigins = https://admin.example\n'
        m.CONF.write_text(self.original)
        m.ROOT_CONFIG.write_text(json.dumps(signed.config(signed.keys()[1])))
        self.calls = []
        self.stack.enter_context(patch.object(m, 'run', side_effect=lambda *args:self.calls.append(args)))
        self.stack.enter_context(patch.object(m.subprocess, 'run', side_effect=lambda args, **kwargs:self.calls.append(tuple(args))))
        self.stack.enter_context(patch.object(m.subprocess, 'check_output', return_value='287.1-0+deb12u3'))
        self.stack.enter_context(patch.object(m.os, 'chown', create=True))

    def test_install_uninstall_reinstall_preserves_password_config_and_secrets(self):
        m = self.m
        m.install(m.ROOT_CONFIG)
        self.assertEqual(m.CONF.read_text(), self.original + m.BLOCK)
        self.assertIn('broker.py', (m.SYSTEMD / 'dci-sso.service').read_text())
        self.assertIn('LoadCredential=', (m.SYSTEMD / 'dci-sso.service').read_text())
        self.assertTrue(m.CLI.is_file())
        m.uninstall()
        self.assertEqual(m.CONF.read_text(), self.original)
        self.assertTrue(m.ROOT_CONFIG.exists())
        self.assertFalse(m.CLI.exists())
        m.install(m.ROOT_CONFIG)
        m.uninstall(); m.uninstall()

    def test_foreign_bearer_prevents_any_service_changes(self):
        m = self.m; m.CONF.write_text('[bearer]\nCommand = other\n')
        with self.assertRaises(ValueError): m.install(m.ROOT_CONFIG)
        self.assertEqual(self.calls, [])
        self.assertFalse(m.STATE.exists())

    def test_legacy_discord_adapter_prevents_installation(self):
        m = self.m; m.LEGACY.write_text('{}')
        with self.assertRaises(ValueError): m.install(m.ROOT_CONFIG)
        self.assertEqual(self.calls, [])

    def test_modified_managed_file_prevents_uninstall(self):
        m = self.m; m.install(m.ROOT_CONFIG)
        (m.TARGET / 'auth.py').write_text('foreign changes')
        self.calls.clear()
        with self.assertRaises(ValueError): m.uninstall()
        self.assertEqual(self.calls, [])
        self.assertTrue(m.STATE.exists())

    def test_wrong_os_refused_before_mutation(self):
        m = self.m; m.OS_RELEASE.write_text('ID=debian\nVERSION_ID="13"\n')
        with self.assertRaises(ValueError): m.install(m.ROOT_CONFIG)
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()

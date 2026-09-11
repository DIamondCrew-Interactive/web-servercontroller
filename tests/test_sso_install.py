"""Real temporary files, mocked Debian commands. Does not prove native systemd/PAM."""
from contextlib import ExitStack
import importlib.util
import json
import os
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
        # The broker must be able to traverse the isolated fixture's root too.
        if os.name == 'posix':
            self.root.chmod(0o711)
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
        if os.name == 'posix':
            # Fixture parents model normal system directories even if the entire
            # test runner inherited umask 077 from sudo -i.
            for directory in self.root.rglob('*'):
                if directory.is_dir():
                    directory.chmod(0o755)
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

    def test_atomic_write_explicitly_applies_requested_mode(self):
        """os.open's mode alone is filtered by the caller's umask."""
        m = self.m
        target = self.root / 'atomic-config'
        with patch.object(m.os, 'chmod', wraps=m.os.chmod) as chmod:
            m.write(target, 'content', 0o644)
        self.assertIn((target.with_name(target.name + '.dci-new'), 0o644),
                      [call.args[:2] for call in chmod.call_args_list])
        self.assertEqual(target.read_text(), 'content')

    def test_state_records_original_config_mode_and_uninstall_uses_it(self):
        m = self.m
        original_mode = m.CONF.stat().st_mode & 0o777
        m.install(m.ROOT_CONFIG)
        state = json.loads(m.STATE.read_text())
        self.assertTrue(state['cockpit_conf']['existed'])
        self.assertEqual(state['cockpit_conf']['mode'], original_mode)
        with patch.object(m, 'write', wraps=m.write) as write:
            m.uninstall()
        self.assertIn((m.CONF, self.original, original_mode),
                      [call.args[:3] for call in write.call_args_list])
        restored = next(call for call in write.call_args_list if call.args[0] == m.CONF)
        self.assertEqual(restored.args[3],
                         (state['cockpit_conf']['uid'], state['cockpit_conf']['gid']))

    @unittest.skipUnless(os.name == 'posix', 'requires actual POSIX permission and umask semantics')
    def test_restrictive_umask_preserves_config_and_broker_access(self):
        m = self.m
        m.CONF.chmod(0o640)
        # Exercise creation of nested directories, not only an existing /usr/local/lib.
        m.TARGET = self.root / 'new-lib' / 'nested' / 'dci-sso'
        previous = os.umask(0o077)
        try:
            m.install(m.ROOT_CONFIG)
            self.assertEqual(m.CONF.stat().st_mode & 0o777, 0o640)
            for directory in [m.TARGET, m.TARGET.parent, m.TARGET.parent.parent]:
                self.assertEqual(directory.stat().st_mode & 0o777, 0o755)
            for filename in ['broker.py', 'assertions.py', 'auth.py', 'accounts.py', 'cli.py', 'grants.py']:
                self.assertEqual((m.TARGET / filename).stat().st_mode & 0o777, 0o644)
            self.assertEqual(m.CLI.stat().st_mode & 0o777, 0o755)
            self.assertEqual(m.ROOT_CONFIG.stat().st_mode & 0o777, 0o600)
            self.assertEqual(m.STATE.stat().st_mode & 0o777, 0o600)
            for unit in m.UNITS:
                self.assertEqual((m.SYSTEMD / unit).stat().st_mode & 0o777, 0o644)
            if os.geteuid() == 0:
                import pwd
                reader = pwd.getpwnam('nobody')
                pid = os.fork()
                if pid == 0:
                    try:
                        os.setgroups([])
                        os.setgid(reader.pw_gid)
                        os.setuid(reader.pw_uid)
                        for filename in ['broker.py', 'assertions.py', 'grants.py']:
                            source = (m.TARGET / filename).read_text()
                            compile(source, filename, 'exec')
                    except BaseException:
                        os._exit(1)
                    os._exit(0)
                _, status = os.waitpid(pid, 0)
                self.assertEqual(os.waitstatus_to_exitcode(status), 0,
                                 'unprivileged child cannot read/compile installed broker sources')
            # Restoration must use the saved preinstall mode, even after mode drift.
            m.CONF.chmod(0o600)
            m.uninstall()
            self.assertEqual(m.CONF.read_text(), self.original)
            self.assertEqual(m.CONF.stat().st_mode & 0o777, 0o640)
        finally:
            os.umask(previous)

    @unittest.skipUnless(os.name == 'posix', 'requires POSIX traversal bits')
    def test_untraversable_existing_ancestor_refused_before_mutation(self):
        m = self.m
        m.TARGET.parent.chmod(0o700)
        config_before = m.ROOT_CONFIG.read_bytes()
        with self.assertRaises(ValueError):
            m.install(m.ROOT_CONFIG)
        self.assertEqual(self.calls, [])
        self.assertFalse(m.TARGET.exists())
        self.assertFalse(m.STATE.exists())
        self.assertEqual(m.CONF.read_text(), self.original)
        self.assertEqual(m.ROOT_CONFIG.read_bytes(), config_before)
        self.assertEqual(m.TARGET.parent.stat().st_mode & 0o777, 0o700)

    def test_missing_production_wsinstance_group_refused_before_mutation(self):
        m = self.m
        def lookup(name):
            if name == 'cockpit-wsinstance':
                raise KeyError(name)
            return types.SimpleNamespace(gr_gid=123)
        with patch.object(m.grp, 'getgrnam', side_effect=lookup) as query:
            with self.assertRaises(KeyError):
                m.install(m.ROOT_CONFIG)
            query.assert_any_call('cockpit-wsinstance')
        self.assertEqual(self.calls, [])
        self.assertFalse(m.STATE.exists())
        self.assertFalse(m.TARGET.exists())
        self.assertEqual(m.CONF.read_text(), self.original)

    @unittest.skipUnless(os.name == 'posix', 'requires actual POSIX permission and umask semantics')
    def test_empty_0700_target_left_by_rollback_is_repaired(self):
        m = self.m
        m.TARGET.mkdir(mode=0o700)
        m.CONF.chmod(0o644)
        previous = os.umask(0o077)
        try:
            m.install(m.ROOT_CONFIG)
            self.assertEqual(m.TARGET.stat().st_mode & 0o777, 0o755)
            self.assertEqual((m.TARGET / 'broker.py').stat().st_mode & 0o777, 0o644)
            self.assertEqual(m.CONF.stat().st_mode & 0o777, 0o644)
            m.uninstall()
            self.assertEqual(m.CONF.read_text(), self.original)
            self.assertEqual(m.CONF.stat().st_mode & 0o777, 0o644)
        finally:
            os.umask(previous)


if __name__ == '__main__':
    unittest.main()

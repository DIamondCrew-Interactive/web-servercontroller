"""Filesystem lifecycle tests with mocked Debian commands; NOT a real dpkg test."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import manage as m


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        upstream = self.root / 'usr/share/cockpit'
        upstream.mkdir(parents=True)
        self.source = self.root / 'source'
        shutil.copytree(m.SOURCE / 'src', self.source / 'src')
        shutil.copytree(m.SOURCE / 'scripts', self.source / 'scripts', ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(m.SOURCE / 'discord', self.source / 'discord', ignore=shutil.ignore_patterns('__pycache__'))
        self.config = {'packages': ['shell'], 'cockpit_version': '287.1-0+deb12u3', 'debian_packages': []}
        (self.source / 'compatibility.json').write_text(json.dumps(self.config))
        (self.source / 'VERSION').write_text('test-1')
        shell = upstream / 'shell'
        shell.mkdir()
        (shell / 'manifest.json').write_text('{"bridges": [{"privileged": true}]}')
        (shell / 'index.html').write_text('<html><head></head><body><nav id="host-apps"></nav></body></html>')
        (shell / 'index.js').write_text('/* unchanged upstream */')
        css = upstream / 'branding/debian/branding.css'
        css.parent.mkdir(parents=True)
        css.write_text('original Debian CSS')
        (upstream / 'static').mkdir()
        (upstream / 'static/login.html').write_text('<html><head></head><body><div id="main"><div id="login" class="login-area" hidden></div></div><div class="details" id="login-details" hidden><p>Server</p></div></body></html>')
        values = {'STATE': self.root / 'state', 'LOCAL': self.root / 'local/cockpit', 'UPSTREAM': upstream,
                  'CSS': css, 'DIVERTED': css.with_name('branding.css.dci-original'), 'LOGO': css.with_name('dc-logo.png'),
                  'HOOK': self.root / 'apt/90dci', 'SOURCE': self.source}
        for key, value in values.items():
            self.stack.enter_context(patch.object(m, key, value))
        m.STATE.mkdir()
        m.HOOK.parent.mkdir()
        self.diverted = False
        self.diversions = {}
        self.fail_link = False
        self.calls = []
        self.stack.enter_context(patch.object(m, 'run', self.mock_run))
        self.stack.enter_context(patch.object(m, 'compatible', lambda: self.config))
        if os.name == 'nt':
            # Windows cannot atomically replace a directory symlink like POSIX rename.
            # Simulate that one primitive; Linux CI exercises the real os.replace.
            real_replace = os.replace
            def windows_replace(src, dst):
                if Path(src).is_symlink() and Path(dst).is_symlink():
                    Path(dst).unlink()
                return real_replace(src, dst)
            self.stack.enter_context(patch.object(os, 'replace', windows_replace))
        real_build = m.build
        self.stack.enter_context(patch.object(m, 'build', lambda u, o: real_build(u, o, self.source)))
        try:
            probe = self.root / 'probe'
            probe.symlink_to(css)
            probe.unlink()
        except OSError as exc:
            self.skipTest(f'OS does not permit symlinks: {exc}')

    def mock_run(self, *args, check=True):
        self.calls.append(args)
        if args[0] == 'systemctl':
            return 'active' if args[1] == 'is-active' else ''
        if args[0] == 'dpkg-divert':
            path = Path(args[-1])
            if '--listpackage' in args:
                return 'LOCAL' if str(path) in self.diversions else ''
            if '--truename' in args:
                return self.diversions.get(str(path), str(path))
            backup = Path(args[args.index('--divert') + 1])
            if '--add' in args:
                path.rename(backup)
                self.diversions[str(path)] = str(backup)
            elif '--remove' in args:
                backup.rename(path)
                del self.diversions[str(path)]
            self.diverted = str(m.CSS) in self.diversions
            return ''
        raise AssertionError(args)

    def test_install_update_rollback_uninstall(self):
        m.install()
        first = m.state()['current']
        self.assertTrue(m.CSS.is_symlink())
        self.assertEqual((m.LOCAL / 'shell/index.js').read_text(), '/* unchanged upstream */')
        self.assertEqual(json.loads((m.LOCAL / 'shell/manifest.json').read_text())['bridges'][0]['privileged'], True)
        (self.source / 'src/theme.css').write_text('/* second theme */')
        m.install()
        self.assertNotEqual(first, m.state()['current'])
        m.rollback()
        self.assertEqual(first, m.state()['current'])
        m.uninstall()
        m.uninstall()  # Idempotent.
        self.assertEqual(m.CSS.read_text(), 'original Debian CSS')
        self.assertFalse(m.CSS.is_symlink())
        self.assertFalse((m.LOCAL / 'shell').exists())
        self.assertFalse(m.HOOK.exists())

    def test_apt_deactivates_then_rebuilds_updated_upstream(self):
        m.install()
        m.uninstall(apt=True)
        self.assertTrue(m.HOOK.exists())
        self.assertFalse(m.state()['active'])
        (m.UPSTREAM / 'shell/index.js').write_text('/* updated upstream */')
        m.install()
        self.assertEqual((m.LOCAL / 'shell/index.js').read_text(), '/* updated upstream */')

    def test_foreign_override_refused(self):
        (m.LOCAL / 'shell').mkdir(parents=True)
        with self.assertRaisesRegex(RuntimeError, 'Conflicting'):
            m.install()
        self.assertFalse(self.diverted)

    def test_modified_override_never_removed(self):
        m.install()
        (m.LOCAL / 'shell').unlink()
        (m.LOCAL / 'shell').mkdir()
        with self.assertRaisesRegex(RuntimeError, 'Foreign'):
            m.uninstall()
        self.assertTrue((m.LOCAL / 'shell').is_dir())

    def test_incompatible_version_no_mutation(self):
        with patch.object(m, 'compatible', side_effect=RuntimeError('Unsupported Cockpit')):
            with self.assertRaises(RuntimeError):
                m.install()
        self.assertEqual(m.CSS.read_text(), 'original Debian CSS')
        self.assertFalse(m.HOOK.exists())

    def test_rollback_rejects_changed_upstream(self):
        m.install()
        m.install()
        (m.UPSTREAM / 'shell/index.js').write_text('new upstream')
        with self.assertRaisesRegex(RuntimeError, 'different upstream'):
            m.rollback()

    def test_rollback_rejects_changed_original_login(self):
        m.install()
        m.install()
        m.login_files()[1].write_text('changed original login')
        with self.assertRaisesRegex(RuntimeError, 'different upstream login'):
            m.rollback()

    def test_failed_first_activation_restores_branding(self):
        original = Path.symlink_to
        def failing(path, target, **kwargs):
            if path == m.LOGO:
                raise OSError('injected disk failure')
            return original(path, target, **kwargs)
        with patch.object(Path, 'symlink_to', failing):
            with self.assertRaises(OSError):
                m.install()
        self.assertFalse(m.state()['active'])
        self.assertEqual(m.CSS.read_text(), 'original Debian CSS')
        self.assertFalse(self.diverted)


if __name__ == '__main__':
    unittest.main()

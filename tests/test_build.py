import gzip
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from build import SOURCE, BRAND, LINK, build, digest, patch_html, patch_catalog

SNAPSHOT = Path(os.environ.get('DCI_UPSTREAM', SOURCE.parent / 'cockpit'))


class BuildTests(unittest.TestCase):
    def test_real_snapshot_only_expected_html_changes(self):
        if not SNAPSHOT.exists():
            self.skipTest('Snapshot not available; never included in release')
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'output'
            report = build(SNAPSHOT, output)
            self.assertEqual(len(report['patched_html']), 14)
            for relative, expected in report['upstream_sha256'].items():
                upstream = SNAPSHOT / relative
                generated = output / 'packages' / relative
                self.assertEqual(digest(upstream), expected)
                if relative in report['patched_html']:
                    text = generated.read_text(encoding='utf-8')
                    text = re.sub(r'<link rel="stylesheet" href="[^"]+" data-dci-theme="1">\n', '', text)
                    text = text.replace(BRAND + '\n', '')
                    self.assertEqual(text, upstream.read_text(encoding='utf-8'))
                elif relative in report['patched_catalogs']:
                    original = gzip.decompress(upstream.read_bytes()).decode('utf-8')
                    translations = json.loads((SOURCE / 'src/locales/cs.json').read_text(encoding='utf-8'))
                    self.assertEqual(gzip.decompress(generated.read_bytes()).decode('utf-8'), patch_catalog(original, translations))
                else:
                    self.assertEqual(generated.read_bytes(), upstream.read_bytes(), relative)
            for relative in report['patched_html']:
                path = output / 'packages' / relative
                href = re.search(r'href="([^"]+)" data-dci-theme', path.read_text())[1]
                self.assertTrue((path.parent / href).resolve().is_file())
            self.assertEqual((output / 'packages/dci_theme/logo.png').read_bytes(), (SOURCE / 'src/assets/logo.png').read_bytes())

    def test_reject_double_patch_and_unknown_head(self):
        original = '<html><head></head><body></body></html>'
        with self.assertRaises(ValueError):
            patch_html(patch_html(original, 'users/index.html'), 'users/index.html')
        for malformed in ['no head', '<head></head><head></head>']:
            with self.assertRaises(ValueError):
                patch_html(malformed, 'users/index.html')

    def test_unknown_shell_layout_rejected(self):
        with self.assertRaises(ValueError):
            patch_html('<html><head></head><body></body></html>', 'shell/index.html')

    def test_nested_link(self):
        self.assertIn('href="../../dci_theme/theme.css"', patch_html('<head></head>', 'users/sub/page.html'))

    def test_failure_removes_partial_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'source'
            source.mkdir()
            (source / 'compatibility.json').write_text(json.dumps({'packages': ['broken']}))
            (source / 'src/locales').mkdir(parents=True)
            (source / 'src/locales/cs.json').write_text('{}')
            upstream = root / 'upstream/broken'
            upstream.mkdir(parents=True)
            (upstream / 'manifest.json').write_text('{}')
            (upstream / 'index.html').write_text('unexpected layout')
            with self.assertRaises(ValueError):
                build(upstream.parent, root / 'out', source)
            self.assertFalse((root / 'out').exists())

    def test_original_snapshot_unchanged(self):
        if not SNAPSHOT.exists():
            self.skipTest('Snapshot not available')
        baseline = json.loads((SOURCE / 'docs/snapshot-sha256.json').read_text())
        self.assertEqual({p.relative_to(SNAPSHOT).as_posix(): digest(p) for p in SNAPSHOT.rglob('*') if p.is_file()}, baseline)


if __name__ == '__main__':
    unittest.main()

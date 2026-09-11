import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import fetch_test_upstream as upstream


def deb(members):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as archive:
        for name, kind in members:
            member = tarfile.TarInfo(name)
            if kind == 'link':
                member.type, member.linkname = tarfile.SYMTYPE, '/etc/shadow'
                archive.addfile(member)
            else:
                member.size = 2
                archive.addfile(member, io.BytesIO(b'{}'))
    payload = stream.getvalue()
    header = f'{"data.tar/":<16}{0:<12}{0:<6}{0:<6}{"100644":<8}{len(payload):<10}`\n'.encode()
    return b'!<arch>\n' + header + payload


class DebianAssetTests(unittest.TestCase):
    def test_only_public_regular_files_are_extracted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            upstream.unpack_ui(deb([('./usr/share/cockpit/shell/manifest.json', 'file'),
                                    ('./etc/cockpit/secret', 'file'),
                                    ('./usr/share/cockpit/shell/unsafe', 'link')]), root)
            self.assertEqual([p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()], ['shell/manifest.json'])
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                upstream.unpack_ui(deb([('./usr/share/cockpit/../../escape', 'file')]), root)

    def test_invalid_cached_deb_rejected_before_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'tests').mkdir()
            (root / 'tests/debian-packages.json').write_text(json.dumps({'version': 'test', 'packages': [
                {'package': 'example', 'url': 'https://example.invalid/unused', 'sha256': hashlib.sha256(b'expected').hexdigest()}
            ]}))
            (root / 'cache').mkdir()
            (root / 'cache/example.deb').write_bytes(b'corrupt')
            with patch.object(upstream, 'SOURCE', root), self.assertRaisesRegex(ValueError, 'Checksum mismatch'):
                upstream.fetch(root / 'output', root / 'cache')
            self.assertFalse((root / 'output').exists())


if __name__ == '__main__':
    unittest.main()

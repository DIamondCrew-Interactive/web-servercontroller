import hashlib
import io
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from package import collect, package


class PackageTests(unittest.TestCase):
    def test_allowlist_reproducibility_and_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            archive = package(destination=output)
            first = archive.read_bytes()
            self.assertEqual(first, package(destination=output).read_bytes())
            with tarfile.open(fileobj=io.BytesIO(first), mode='r:gz') as tar:
                members = tar.getmembers()
                for member in members:
                    self.assertTrue(member.isfile())
                    self.assertFalse(any(part in {'etc-cockpit', 'cockpit', 'build', 'node_modules'} for part in Path(member.name).parts))
                    self.assertNotIn(Path(member.name).suffix, {'.key', '.cert', '.pem'})
                manifest = next(m for m in members if m.name.endswith('/MANIFEST.sha256'))
                prefix = manifest.name.rsplit('/', 1)[0]
                for line in tar.extractfile(manifest).read().decode().splitlines():
                    checksum, relative = line.split('  ', 1)
                    self.assertEqual(hashlib.sha256(tar.extractfile(prefix + '/' + relative).read()).hexdigest(), checksum)
                for member in members:
                    if member.name.endswith('.sh'):
                        self.assertEqual(member.mode, 0o755)


if __name__ == '__main__':
    unittest.main()

#!/usr/bin/env python3
"""Create a local, reproducible source archive from an explicit allowlist. No upload."""
import gzip
import hashlib
import io
from pathlib import Path
import re
import tarfile
from build import SOURCE

TOP_FILES = ['VERSION', 'compatibility.json', 'README.md', 'CHANGELOG.md', 'NOTICE.md', 'package.json', 'package-lock.json', '.gitignore', '.gitattributes', '.github/workflows/release.yml']
DIRECTORIES = {'src': {'.css', '.png', '.js', '.json'}, 'scripts': {'.py', '.sh'},
               'discord': {'.py', '.json', '.js', '.html', '.css', '.service', '.socket', '.example'},
               'tests': {'.py', '.cjs', '.json'}, 'preview': {'.css', '.js', '.html'},
               'docs': {'.md', '.json'}}


def collect(source=SOURCE):
    files = [source / name for name in TOP_FILES]
    for directory, suffixes in DIRECTORIES.items():
        files.extend(p for p in (source / directory).rglob('*') if p.is_file() and p.suffix in suffixes and '__pycache__' not in p.parts)
    for path in files:
        if path.is_symlink() or not path.resolve().is_relative_to(source.resolve()):
            raise ValueError(f'Unexpected source symlink: {path}')
        content = path.read_bytes()
        patterns = [rb'-----BEGIN [A-Z ]*PRIVATE KEY-----', rb'gh[pousr]_[A-Za-z0-9]{30,}', rb'github_pat_[A-Za-z0-9_]{30,}', rb'AKIA[A-Z0-9]{16}']
        if any(re.search(pattern, content) for pattern in patterns):
            raise ValueError(f'Credential-like content in {path.name}; release aborted')
    return sorted(files, key=lambda path: path.relative_to(source).as_posix())


def package(source=SOURCE, destination=None):
    files = collect(source)
    version = (source / 'VERSION').read_text().strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Invalid version')
    prefix = f'diamondcrew-servercontroller-{version}'
    destination = destination or source / 'dist'
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / (prefix + '.tar.gz')
    hashes = []
    with archive.open('wb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as zipped, tarfile.open(fileobj=zipped, mode='w') as tar:
        for file in files:
            relative = file.relative_to(source).as_posix()
            content = file.read_bytes()
            if file.suffix != '.png':
                content = content.replace(b'\r\n', b'\n')
            hashes.append(hashlib.sha256(content).hexdigest() + '  ' + relative)
            info = tarfile.TarInfo(prefix + '/' + relative)
            info.size = len(content)
            info.mode = 0o755 if file.suffix == '.sh' else 0o644
            tar.addfile(info, io.BytesIO(content))
        manifest = ('\n'.join(hashes) + '\n').encode()
        info = tarfile.TarInfo(prefix + '/MANIFEST.sha256')
        info.size, info.mode = len(manifest), 0o644
        tar.addfile(info, io.BytesIO(manifest))
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    (destination / 'SHA256SUMS').write_text(checksum + '  ' + archive.name + '\n')
    print(f'{archive}: {len(files)} source files; SHA256 {checksum}')
    return archive


if __name__ == '__main__':
    package()

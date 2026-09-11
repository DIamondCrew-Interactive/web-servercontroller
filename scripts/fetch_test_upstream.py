#!/usr/bin/env python3
"""Download checksum-pinned public Debian UI assets for tests, without installing .deb files."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import tarfile
import time
import urllib.request

SOURCE = Path(__file__).resolve().parents[1]


def unpack_ui(data, output):
    if not data.startswith(b'!<arch>\n'):
        raise ValueError('Not a Debian ar archive')
    offset = 8
    while offset < len(data):
        header = data[offset:offset + 60]
        if len(header) != 60 or header[58:60] != b'`\n':
            raise ValueError('Invalid ar header')
        size = int(header[48:58])
        name = header[:16].decode('ascii').strip().rstrip('/')
        payload = data[offset + 60:offset + 60 + size]
        if len(payload) != size:
            raise ValueError('Truncated Debian archive')
        if name.startswith('data.tar'):
            with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
                for member in archive:
                    path = PurePosixPath(member.name)
                    # Only public regular UI files; no maintainer scripts, etc/, links or devices.
                    if path.parts[:3] != ('usr', 'share', 'cockpit') or not member.isfile():
                        continue
                    relative = PurePosixPath(*path.parts[3:])
                    if '..' in relative.parts or relative.is_absolute():
                        raise ValueError('Unsafe archive path')
                    target = output.joinpath(*relative.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.extractfile(member).read())
            return
        offset += 60 + size + size % 2
    raise ValueError('Debian archive contains no data.tar')


def fetch(output, cache):
    if output.exists():
        raise ValueError(f'Output must not exist: {output}')
    lock = json.loads((SOURCE / 'tests/debian-packages.json').read_text(encoding='utf-8'))
    cache.mkdir(parents=True, exist_ok=True)
    # Verify every complete download before creating the output tree.
    packages = []
    for package in lock['packages']:
        file = cache / (package['package'] + '.deb')
        if not file.exists():
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(package['url'], timeout=60) as response:
                        payload = response.read()
                    break
                except OSError:
                    if attempt == 2:
                        raise
                    time.sleep(2)
            if hashlib.sha256(payload).hexdigest() != package['sha256']:
                raise ValueError(f'Checksum mismatch: {package["package"]}')
            file.write_bytes(payload)
        data = file.read_bytes()
        if hashlib.sha256(data).hexdigest() != package['sha256']:
            raise ValueError(f'Checksum mismatch: {file}')
        packages.append(data)
    output.mkdir(parents=True)
    for data in packages:
        unpack_ui(data, output)
    print(f'Public Debian {lock["version"]} UI assets verified and extracted to {output}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=SOURCE / 'build/upstream')
    parser.add_argument('--cache', type=Path, default=SOURCE / 'build/debian')
    args = parser.parse_args()
    fetch(args.output, args.cache)

#!/usr/bin/env python3
"""Opt-in Debian installer for Discord authentication; run separately from the theme."""
import argparse
import grp
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess

from oauth import validate_config

SOURCE = Path(__file__).resolve().parent
TARGET = Path('/usr/local/lib/dci-discord')
STATE = Path('/var/lib/diamondcrew-discord-install.json')
CONF = Path('/etc/cockpit/cockpit.conf')
BLOCK = '\n# BEGIN DiamondCrew Interactive Discord\n[bearer]\nUnixPath = /run/dci-discord-auth.sock\n# END DiamondCrew Interactive Discord\n'
UNITS = ['dci-discord.service', 'dci-discord-auth.socket', 'dci-discord-auth@.service']


def run(*args):
    subprocess.run(args, check=True)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, text, mode=0o600):
    temporary = path.with_name(path.name + '.dci-new')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        stream.write(text)
    os.replace(temporary, path)


def uninstall():
    if not STATE.exists():
        print('Discord authentication is not installed by this tool.')
        return
    state = json.loads(STATE.read_text())
    for name, checksum in state['files'].items():
        path = Path(name)
        if path.exists() and (path.is_symlink() or sha(path) != checksum):
            raise ValueError(f'Modified managed file; refusing to delete {path}')
    config = CONF.read_text() if CONF.exists() else ''
    if BLOCK not in config and re.search(r'^\[bearer\]', config, re.M | re.I):
        raise ValueError('Bearer configuration changed; resolve it before uninstall')
    # Close OAuth sessions as well as the listener before removing authentication code.
    subprocess.run(['systemctl', 'stop', 'dci-discord-auth@*.service'], check=True)
    run('systemctl', 'disable', '--now', 'dci-discord-auth.socket', 'dci-discord.service')
    if BLOCK in config:
        mode = CONF.stat().st_mode & 0o777
        write(CONF, config.replace(BLOCK, '', 1), mode)
    for name in state['files']:
        Path(name).unlink(missing_ok=True)
    STATE.unlink()
    run('systemctl', 'daemon-reload')
    run('systemctl', 'try-restart', 'cockpit.service')
    print('Discord authentication removed. PAM password login preserved; mappings and secret configuration retained.')


def install(config_path):
    if STATE.exists():
        raise ValueError('Uninstall the previous Discord adapter before installing a replacement')
    if Path('/etc/os-release').read_text().find('ID=debian') < 0:
        raise ValueError('Debian required')
    version = subprocess.check_output(['dpkg-query', '-W', '-f=${Version}', 'cockpit-ws'], text=True)
    if version != '287.1-0+deb12u3':
        raise ValueError('Cockpit 287.1-0+deb12u3 required')
    grp.getgrnam('cockpit-ws')
    grp.getgrnam('www-data')
    config = validate_config(json.loads(config_path.read_text(encoding='utf-8')))
    current = CONF.read_text() if CONF.exists() else ''
    if re.search(r'^\s*\[bearer\]', current, re.M | re.I) or 'BEGIN DiamondCrew Interactive Discord' in current:
        raise ValueError('Existing bearer authentication must not be overwritten')
    files = {SOURCE / name: TARGET / name for name in ['oauth.py', 'accounts.py', 'auth.py']}
    files.update({SOURCE / 'systemd' / name: Path('/etc/systemd/system') / name for name in UNITS})
    if TARGET.exists() and any(TARGET.iterdir()):
        raise ValueError('Non-empty existing adapter directory')
    if any(path.exists() or path.is_symlink() for path in files.values()):
        raise ValueError('Conflicting adapter files')
    try:
        account = pwd.getpwnam('dci-discord')
        if account.pw_uid >= 1000 or account.pw_shell != '/usr/sbin/nologin':
            raise ValueError('Unexpected existing service account')
    except KeyError:
        run('useradd', '--system', '--user-group', '--home-dir', '/var/lib/dci-discord', '--no-create-home', '--shell', '/usr/sbin/nologin', 'dci-discord')
    destination = Path('/etc/dci-discord/oauth.json')
    destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    if destination.resolve() != config_path.resolve():
        if destination.exists() or destination.is_symlink():
            raise ValueError('Existing OAuth configuration; supply that path explicitly')
        write(destination, json.dumps(config, indent=2) + '\n', 0o640)
    if destination.is_symlink():
        raise ValueError('OAuth configuration may not be a symlink')
    os.chown(destination, 0, grp.getgrnam('dci-discord').gr_gid)
    destination.chmod(0o640)
    TARGET.mkdir(parents=True, exist_ok=True, mode=0o755)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    write(STATE, json.dumps({'files': {str(target): sha(source) for source, target in files.items()}}))
    for source, target in files.items():
        shutil.copyfile(source, target)
        target.chmod(0o644)
    CONF.parent.mkdir(parents=True, exist_ok=True)
    write(CONF, current + BLOCK, CONF.stat().st_mode & 0o777 if CONF.exists() else 0o644)
    run('systemctl', 'daemon-reload')
    run('systemctl', 'enable', '--now', 'dci-discord.service', 'dci-discord-auth.socket')
    run('systemctl', 'try-restart', 'cockpit.service')
    print('Adapter installed. Configure the /discord/ HTTPS reverse proxy and explicitly link existing accounts.')


if __name__ == '__main__':
    if os.geteuid() != 0:
        raise SystemExit('Run as root over SSH')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install', 'uninstall'])
    parser.add_argument('--config', type=Path, default=Path('/etc/dci-discord/oauth.json'))
    args = parser.parse_args()
    try:
        install(args.config) if args.action == 'install' else uninstall()
    except Exception as error:
        # Never print config values or OAuth responses.
        print('Discord adapter operation failed. Review configuration and use this script with uninstall to recover.', file=__import__('sys').stderr)
        raise SystemExit(1)

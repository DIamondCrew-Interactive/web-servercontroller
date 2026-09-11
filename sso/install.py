#!/usr/bin/env python3
"""Opt-in Debian installer for Staff SSO authentication; run separately from the theme."""
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

from broker import validate_config

SOURCE = Path(__file__).resolve().parent
TARGET = Path('/usr/local/lib/dci-sso')
STATE = Path('/var/lib/diamondcrew-sso-install.json')
CONF = Path('/etc/cockpit/cockpit.conf')
ROOT_CONFIG = Path('/etc/diamondcrew-servercontroller/sso.json')
OS_RELEASE = Path('/etc/os-release')
SYSTEMD = Path('/etc/systemd/system')
CLI = Path('/usr/local/bin/dci-servercontroller')
LEGACY = Path('/var/lib/diamondcrew-discord-install.json')
BLOCK = '\n# BEGIN DiamondCrew Interactive SSO\n[bearer]\nUnixPath = /run/dci-sso-auth.sock\n# END DiamondCrew Interactive SSO\n'
UNITS = ['dci-sso.service', 'dci-sso-auth.socket', 'dci-sso-auth@.service']


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
        print('Staff SSO authentication is not installed by this tool.')
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
    subprocess.run(['systemctl', 'stop', 'dci-sso-auth@*.service'], check=True)
    run('systemctl', 'disable', '--now', 'dci-sso-auth.socket', 'dci-sso.service')
    if BLOCK in config:
        mode = CONF.stat().st_mode & 0o777
        write(CONF, config.replace(BLOCK, '', 1), mode)
    for name in state['files']:
        Path(name).unlink(missing_ok=True)
    STATE.unlink()
    run('systemctl', 'daemon-reload')
    run('systemctl', 'try-restart', 'cockpit.service')
    print('Staff SSO authentication removed. PAM password login preserved; mappings and secret configuration retained.')


def install(config_path):
    if STATE.exists():
        raise ValueError('Uninstall the previous Staff SSO adapter before installing a replacement')
    if LEGACY.exists():
        raise ValueError('Uninstall the old independent Discord adapter using its original installer first')
    for directory in [TARGET, TARGET.parent, ROOT_CONFIG.parent, CONF.parent, SYSTEMD, CLI.parent]:
        if directory.is_symlink():
            raise ValueError('Managed directories may not be symlinks')
        if directory.exists():
            metadata = directory.stat()
            if not directory.is_dir() or (os.name == 'posix' and os.geteuid() == 0 and (metadata.st_uid != 0 or metadata.st_mode & 0o022)):
                raise ValueError('Managed directories must be root-owned and not writable by other users')
    release = dict(line.split('=', 1) for line in OS_RELEASE.read_text().splitlines() if '=' in line)
    if release.get('ID', '').strip('"') != 'debian' or release.get('VERSION_ID', '').strip('"') != '12':
        raise ValueError('Debian 12 required')
    version = subprocess.check_output(['dpkg-query', '-W', '-f=${Version}', 'cockpit-ws'], text=True)
    if version != '287.1-0+deb12u3':
        raise ValueError('Cockpit 287.1-0+deb12u3 required')
    grp.getgrnam('cockpit-ws')
    grp.getgrnam('www-data')
    config = validate_config(json.loads(config_path.read_text(encoding='utf-8')))
    current = CONF.read_text() if CONF.exists() else ''
    if re.search(r'^\s*\[bearer\]', current, re.M | re.I) or 'BEGIN DiamondCrew Interactive SSO' in current:
        raise ValueError('Existing bearer authentication must not be overwritten')
    files = {SOURCE / name: TARGET / name for name in ['broker.py', 'assertions.py', 'grants.py', 'accounts.py', 'auth.py', 'cli.py']}
    files[SOURCE / 'dci-servercontroller.sh'] = CLI
    files.update({SOURCE / 'systemd' / name: SYSTEMD / name for name in UNITS})
    if TARGET.exists() and any(TARGET.iterdir()):
        raise ValueError('Non-empty existing adapter directory')
    if any(path.exists() or path.is_symlink() for path in files.values()):
        raise ValueError('Conflicting adapter files')
    try:
        account = pwd.getpwnam('dci-sso')
        if account.pw_uid >= 1000 or account.pw_shell != '/usr/sbin/nologin':
            raise ValueError('Unexpected existing service account')
    except KeyError:
        run('useradd', '--system', '--user-group', '--home-dir', '/var/lib/dci-sso', '--no-create-home', '--shell', '/usr/sbin/nologin', 'dci-sso')
    destination = ROOT_CONFIG
    destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    if destination.resolve() != config_path.resolve():
        if destination.exists() or destination.is_symlink():
            raise ValueError('Existing OAuth configuration; supply that path explicitly')
        write(destination, json.dumps(config, indent=2) + '\n', 0o600)
    if destination.is_symlink():
        raise ValueError('OAuth configuration may not be a symlink')
    os.chown(destination, 0, 0)
    destination.chmod(0o600)
    TARGET.mkdir(parents=True, exist_ok=True, mode=0o755)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    write(STATE, json.dumps({'files': {str(target): sha(source) for source, target in files.items()}}))
    for source, target in files.items():
        shutil.copyfile(source, target)
        target.chmod(0o755 if target.name == 'dci-servercontroller' else 0o644)
    CONF.parent.mkdir(parents=True, exist_ok=True)
    write(CONF, current + BLOCK, CONF.stat().st_mode & 0o777 if CONF.exists() else 0o644)
    run('systemctl', 'daemon-reload')
    run('systemctl', 'enable', '--now', 'dci-sso.service', 'dci-sso-auth.socket')
    run('systemctl', 'try-restart', 'cockpit.service')
    print('Adapter installed. Configure the /auth/sso/ HTTPS reverse proxy and explicitly link existing accounts.')


if __name__ == '__main__':
    if os.geteuid() != 0:
        raise SystemExit('Run as root over SSH')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install', 'update', 'uninstall'])
    parser.add_argument('--config', type=Path, default=Path('/etc/diamondcrew-servercontroller/sso.json'))
    args = parser.parse_args()
    try:
        if args.action == 'update':
            validate_config(json.loads(args.config.read_text(encoding='utf-8')))
            uninstall()
            install(args.config)
        elif args.action == 'install':
            install(args.config)
        else:
            uninstall()
    except Exception as error:
        # Never print config values or OAuth responses.
        print('Staff SSO adapter operation failed. Review configuration and use this script with uninstall to recover.', file=__import__('sys').stderr)
        raise SystemExit(1)

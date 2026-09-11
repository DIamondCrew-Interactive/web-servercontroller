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
import stat
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


def write(path, text, mode=0o600, owner=None):
    temporary = path.with_name(path.name + '.dci-new')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text)
        if owner is not None:
            os.chown(temporary, *owner)
        # os.open's mode is masked by the caller's umask, including sudo -i 077.
        # Apply the exact intended permissions before publishing the new file.
        temporary.chmod(mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def ensure_directory(path):
    """Create only missing directories with explicit permissions, never chmod parents."""
    missing = []
    current = path
    while not current.exists():
        if current.is_symlink():
            raise ValueError('Managed directories may not be symlinks')
        missing.append(current)
        current = current.parent
    if current.is_symlink() or not current.is_dir():
        raise ValueError('Managed directories must be real directories')
    for directory in reversed(missing):
        directory.mkdir(mode=0o755)
        directory.chmod(0o755)


def require_traversal(path):
    """The non-root broker must traverse every existing code-path ancestor."""
    for directory in (path, *path.parents):
        if directory.is_symlink():
            raise ValueError('Runtime directory ancestors may not be symlinks')
        if directory.exists() and (not directory.is_dir() or
                (os.name == 'posix' and not directory.stat().st_mode & 0o001)):
            raise ValueError(f'Existing runtime parent must be traversable: {directory}')


def config_metadata():
    if CONF.is_symlink() or (CONF.exists() and not CONF.is_file()):
        raise ValueError('Cockpit configuration must be a regular non-symlink file')
    if not CONF.exists():
        return {'existed': False, 'mode': None, 'uid': None, 'gid': None}
    metadata = CONF.stat()
    return {'existed': True, 'mode': stat.S_IMODE(metadata.st_mode),
            'uid': metadata.st_uid, 'gid': metadata.st_gid}


def uninstall():
    if not STATE.exists():
        print('Staff SSO authentication is not installed by this tool.')
        return
    state = json.loads(STATE.read_text())
    present_conf = config_metadata()
    original_conf = state.get('cockpit_conf', present_conf)
    if (not isinstance(original_conf, dict) or
            type(original_conf.get('existed')) is not bool or
            (original_conf['existed'] and
             (type(original_conf.get('mode')) is not int or
              not 0 <= original_conf['mode'] <= 0o7777 or
              any(type(original_conf.get(key)) is not int or original_conf[key] < 0
                  for key in ('uid', 'gid'))))):
        raise ValueError('Invalid saved Cockpit configuration metadata')
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
        restored = config.replace(BLOCK, '', 1)
        if not original_conf['existed'] and not restored:
            CONF.unlink()
        else:
            metadata = original_conf if original_conf['existed'] else present_conf
            write(CONF, restored, metadata['mode'], (metadata['uid'], metadata['gid']))
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
    # TARGET itself is our empty, root-owned code directory and may be repaired
    # below. Unrelated existing parent directories are never made more public.
    require_traversal(TARGET.parent)
    require_traversal(CLI.parent)
    original_conf = config_metadata()
    release = dict(line.split('=', 1) for line in OS_RELEASE.read_text().splitlines() if '=' in line)
    if release.get('ID', '').strip('"') != 'debian' or release.get('VERSION_ID', '').strip('"') != '12':
        raise ValueError('Debian 12 required')
    version = subprocess.check_output(['dpkg-query', '-W', '-f=${Version}', 'cockpit-ws'], text=True)
    if version != '287.1-0+deb12u3':
        raise ValueError('Cockpit 287.1-0+deb12u3 required')
    grp.getgrnam('cockpit-wsinstance')
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
    ensure_directory(destination.parent)
    if destination.resolve() != config_path.resolve():
        if destination.exists() or destination.is_symlink():
            raise ValueError('Existing OAuth configuration; supply that path explicitly')
        write(destination, json.dumps(config, indent=2) + '\n', 0o600)
    if destination.is_symlink():
        raise ValueError('OAuth configuration may not be a symlink')
    os.chown(destination, 0, 0)
    destination.chmod(0o600)
    ensure_directory(TARGET)
    TARGET.chmod(0o755)
    ensure_directory(STATE.parent)
    ensure_directory(SYSTEMD)
    ensure_directory(CLI.parent)
    ensure_directory(CONF.parent)
    write(STATE, json.dumps({'cockpit_conf': original_conf,
                            'files': {str(target): sha(source) for source, target in files.items()}}))
    for source, target in files.items():
        shutil.copyfile(source, target)
        target.chmod(0o755 if target.name == 'dci-servercontroller' else 0o644)
    owner = (original_conf['uid'], original_conf['gid']) if original_conf['existed'] else None
    write(CONF, current + BLOCK, original_conf['mode'] if original_conf['existed'] else 0o644, owner)
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

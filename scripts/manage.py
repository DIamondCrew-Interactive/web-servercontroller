#!/usr/bin/env python3
"""Debian lifecycle for the DiamondCrew Interactive Cockpit theme (stdlib only)."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

from build import SOURCE, build, inventory

STATE = Path('/var/lib/diamondcrew-servercontroller')
LOCAL = Path('/usr/local/share/cockpit')
UPSTREAM = Path('/usr/share/cockpit')
CSS = UPSTREAM / 'branding/debian/branding.css'
DIVERTED = CSS.with_name('branding.css.dci-original')
LOGO = CSS.with_name('dc-logo.png')
HOOK = Path('/etc/apt/apt.conf.d/90diamondcrew-servercontroller')
HOOK_TEXT = ('// DiamondCrew Interactive managed: deactivate before Debian package updates.\n'
             'DPkg::Pre-Invoke { "if test -f /var/lib/diamondcrew-servercontroller/current/source/scripts/manage.py; '
             'then /usr/bin/python3 /var/lib/diamondcrew-servercontroller/current/source/scripts/manage.py apt-pre; fi"; };\n')


def run(*args, check=True):
    return subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check).stdout.strip()


def exists(path):
    return path.exists() or path.is_symlink()


def atomic_json(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    temp.chmod(0o644)
    os.replace(temp, path)


def state():
    path = STATE / 'state.json'
    return json.loads(path.read_text()) if path.exists() else {'active': False}


def save(value):
    atomic_json(STATE / 'state.json', value)


def owned_link(path, target):
    return path.is_symlink() and link_target(path) == target


def link_target(path):
    # Windows prefix normalization allows filesystem simulations on the dev host.
    raw = os.readlink(path)
    if os.name == 'nt' and raw.startswith('\\\\?\\'):
        raw = raw[4:]
    return Path(raw)


def point(path, target):
    temp = path.with_name(path.name + '.dci-new')
    if exists(temp):
        raise RuntimeError(f'Unexpected temporary path: {temp}')
    temp.symlink_to(target, target_is_directory=target.is_dir())
    try:
        os.replace(temp, path)
    finally:
        if owned_link(temp, target):
            temp.unlink()


def compatible():
    config = json.loads((SOURCE / 'compatibility.json').read_text())
    os_release = {}
    for line in Path('/etc/os-release').read_text().splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            os_release[key] = value.strip('"')
    if os_release.get('ID') != 'debian' or os_release.get('VERSION_ID') != '12' or os_release.get('VARIANT_ID'):
        raise RuntimeError('Supported target: Debian 12 without an OS branding variant')
    for package in config['debian_packages']:
        value = run('dpkg-query', '-W', '-f=${Status}\t${Version}', package)
        if value != 'install ok installed\t' + config['cockpit_version']:
            raise RuntimeError(f'Unsupported {package}: {value}; required {config["cockpit_version"]}')
    return config


@contextmanager
def maintenance():
    # System package resources must not be changed while Cockpit is serving them.
    units = ['cockpit.socket', 'cockpit.service']
    active = [u for u in units if run('systemctl', 'is-active', u, check=False) == 'active']
    run('systemctl', 'stop', *units)
    try:
        yield
    finally:
        if active:
            run('systemctl', 'start', *active)


def diversion_owner():
    return run('dpkg-divert', '--listpackage', str(CSS))


def verify_owned(data):
    for name in data.get('packages', []):
        path = LOCAL / name
        if exists(path) and not owned_link(path, STATE / 'current/packages' / name):
            raise RuntimeError(f'Foreign or modified override; refusing to remove: {path}')
    for path, target in [(CSS, STATE / 'current/branding/branding.css'), (LOGO, STATE / 'current/branding/dc-logo.png')]:
        # CSS can already be restored when recovering an interrupted deactivation.
        if exists(path) and not owned_link(path, target):
            if path == CSS and not diversion_owner():
                continue
            raise RuntimeError(f'Foreign or modified branding: {path}')
    if diversion_owner() and (diversion_owner() != 'LOCAL' or run('dpkg-divert', '--truename', str(CSS)) != str(DIVERTED)):
        raise RuntimeError('Branding diversion belongs to another installation')


def deactivate(data):
    verify_owned(data)
    for name in data.get('packages', []):
        path = LOCAL / name
        if owned_link(path, STATE / 'current/packages' / name):
            path.unlink()
    if owned_link(LOGO, STATE / 'current/branding/dc-logo.png'):
        LOGO.unlink()
    if owned_link(CSS, STATE / 'current/branding/branding.css'):
        CSS.unlink()
    if diversion_owner():
        run('dpkg-divert', '--local', '--rename', '--remove', '--divert', str(DIVERTED), str(CSS))
    data['active'] = False
    save(data)


def install():
    config = compatible()
    data = state()
    names = config['packages'] + ['dci_theme']
    if data.get('active'):
        verify_owned(data)
        if set(data['packages']) != set(names):
            raise RuntimeError('Package set changed; uninstall before installing this theme version')
    else:
        for path in [*(LOCAL / n for n in names), LOGO, DIVERTED]:
            if exists(path):
                raise RuntimeError(f'Conflicting local file: {path}')
        if diversion_owner() or CSS.is_symlink() or not CSS.is_file():
            raise RuntimeError('Expected original Debian branding.css without a diversion')
    if exists(HOOK) and HOOK.read_text() != HOOK_TEXT:
        raise RuntimeError(f'Foreign APT hook: {HOOK}')
    generation = STATE / 'generations' / (time.strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8])
    report = build(UPSTREAM, generation)
    # Keep the exact management tools with each generation; no snapshot/config files.
    for directory in ['scripts', 'src']:
        shutil.copytree(SOURCE / directory, generation / 'source' / directory, ignore=shutil.ignore_patterns('__pycache__'))
    for filename in ['VERSION', 'compatibility.json']:
        shutil.copyfile(SOURCE / filename, generation / 'source' / filename)
    for path in (generation / 'source').rglob('*'):
        path.chmod(0o755 if path.is_dir() else 0o644)
    (generation / 'source').chmod(0o755)
    current = STATE / 'current'
    old = str(link_target(current)) if current.is_symlink() else None
    if exists(current) and not current.is_symlink():
        raise RuntimeError(f'Unexpected current pointer: {current}')
    with maintenance():
        if inventory(UPSTREAM, config['packages']) != report['upstream_sha256']:
            raise RuntimeError('Upstream changed before activation')
        pending = {**data, 'packages': names, 'active': True}
        save(pending)  # Recovery metadata exists before the first system mutation.
        try:
            point(current, generation)
            LOCAL.mkdir(parents=True, exist_ok=True)
            if not data.get('active'):
                run('dpkg-divert', '--local', '--rename', '--add', '--divert', str(DIVERTED), str(CSS))
                CSS.symlink_to(STATE / 'current/branding/branding.css')
                LOGO.symlink_to(STATE / 'current/branding/dc-logo.png')
                for name in names:
                    (LOCAL / name).symlink_to(STATE / 'current/packages' / name, target_is_directory=True)
            HOOK.write_text(HOOK_TEXT)
            HOOK.chmod(0o644)
            save({**pending, 'current': str(generation), 'previous': old})
        except BaseException:
            if data.get('active') and old:
                point(current, Path(old))
                save(data)
            else:
                deactivate(pending)
            raise
    print(f'DiamondCrew Interactive / Server Controller {report["theme_version"]} active. Log in again and hard-refresh.')


def uninstall(apt=False):
    data = state()
    if data.get('active'):
        with maintenance():
            deactivate(data)
        print('Original Cockpit restored. Theme generations retained for audit.')
    if not apt and HOOK.exists():
        if HOOK.read_text() != HOOK_TEXT:
            raise RuntimeError('Modified APT hook; refusing to delete')
        HOOK.unlink()
    if apt:
        print('DiamondCrew theme inactive for package maintenance. Run update.sh after the upgrade; unsupported Cockpit stays upstream.')


def rollback():
    compatible()
    data = state()
    previous = data.get('previous')
    if not data.get('active') or not previous:
        raise RuntimeError('No active previous generation. Use uninstall for original Cockpit.')
    target = Path(previous)
    if not target.resolve().is_relative_to((STATE / 'generations').resolve()):
        raise RuntimeError('Invalid previous generation path')
    report = json.loads((target / 'build.json').read_text())
    config = json.loads((SOURCE / 'compatibility.json').read_text())
    if report['cockpit_version'] != config['cockpit_version'] or report['upstream_sha256'] != inventory(UPSTREAM, config['packages']):
        raise RuntimeError('Previous generation uses different upstream files; uninstall or rebuild instead')
    verify_owned(data)
    with maintenance():
        point(STATE / 'current', target)
        save({**data, 'current': previous, 'previous': data['current']})
    print('Previous theme generation restored. Log in again and hard-refresh.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install', 'update', 'uninstall', 'rollback', 'apt-pre', 'status'])
    args = parser.parse_args()
    if sys.platform != 'linux' or os.geteuid() != 0:
        parser.error('Lifecycle commands require root on Debian; build.py supports local snapshots')
    import fcntl
    STATE.mkdir(parents=True, exist_ok=True, mode=0o755)
    STATE.chmod(0o755)
    with (STATE / 'lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.action in ['install', 'update']:
            install()
        elif args.action in ['uninstall', 'apt-pre']:
            uninstall(apt=args.action == 'apt-pre')
        elif args.action == 'rollback':
            rollback()
        else:
            print(json.dumps(state(), indent=2))


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        if isinstance(exc, subprocess.CalledProcessError):
            print(exc.stderr, file=sys.stderr)
        print('If activation was interrupted, run uninstall.sh from a root SSH session to recover.', file=sys.stderr)
        sys.exit(1)

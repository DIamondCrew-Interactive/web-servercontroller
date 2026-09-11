#!/usr/bin/env python3
"""Root-only Discord ID to existing local UID mapping. No automatic account creation."""
import argparse
import json
import os
from pathlib import Path
import re

MAPPING = Path('/etc/diamondcrew-servercontroller/discord-users.json')


def eligible(account):
    return 1000 <= account.pw_uid < 65534 and account.pw_shell not in ('', '/bin/false', '/usr/sbin/nologin', '/sbin/nologin')


def read_mapping():
    if not MAPPING.exists():
        return {}
    stat = MAPPING.stat()
    if not MAPPING.is_file() or MAPPING.is_symlink() or stat.st_uid != 0 or stat.st_mode & 0o077:
        raise ValueError('Account mappings must be a root-owned regular file with mode 0600')
    return json.loads(MAPPING.read_text(encoding='utf-8'))


def linked_user(discord_id):
    import pwd
    record = read_mapping().get(discord_id)
    if not record:
        raise ValueError('Discord account is not linked')
    account = pwd.getpwnam(record['username'])
    if not eligible(account) or account.pw_uid != record['uid']:
        raise ValueError('Linked Unix identity changed or is not eligible')
    denied = Path('/etc/cockpit/disallowed-users')
    if denied.exists() and account.pw_name in [line.split('#', 1)[0].strip() for line in denied.read_text().splitlines()]:
        raise ValueError('Cockpit account is disallowed')
    return account


def main():
    import fcntl
    import pwd
    if os.geteuid() != 0:
        raise SystemExit('Administrative access required')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['list', 'show', 'link', 'unlink'])
    parser.add_argument('--user')
    parser.add_argument('--discord-id')
    args = parser.parse_args()
    MAPPING.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    with (MAPPING.parent / 'accounts.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        records = read_mapping()
        if args.action == 'list':
            return print(json.dumps({'users': [a.pw_name for a in pwd.getpwall() if eligible(a)], 'links': records}))
        if args.action == 'show':
            selected = {key: value for key, value in records.items() if key == args.discord_id or (args.user and value['username'] == args.user)}
            if not selected:
                raise ValueError('Identity is not linked')
            return print(json.dumps({'links': selected}))
        if args.action == 'unlink':
            if args.discord_id:
                if args.discord_id not in records:
                    raise ValueError('Discord ID is not linked')
                records.pop(args.discord_id)
            elif args.user:
                records = {key: value for key, value in records.items() if value['username'] != args.user}
            else:
                parser.error('--discord-id or --user is required')
        elif not args.user:
            parser.error('--user is required')
        if args.action == 'link':
            account = pwd.getpwnam(args.user)
            if not eligible(account):
                raise ValueError('Only existing non-system login accounts can be linked')
            if not re.fullmatch(r'[0-9]{17,20}', args.discord_id or ''):
                raise ValueError('Discord ID must be a numeric snowflake, not a username')
            if args.discord_id in records or any(r['username'] == args.user for r in records.values()):
                raise ValueError('Identity already linked. Unlink explicitly before changing it.')
            records[args.discord_id] = {'username': args.user, 'uid': account.pw_uid}
        temp = MAPPING.with_suffix('.new')
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as output:
            json.dump(records, output, indent=2)
            output.write('\n')
        os.replace(temp, MAPPING)
        print(json.dumps({'ok': True}))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError) as error:
        raise SystemExit(str(error))

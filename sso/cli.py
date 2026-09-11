#!/usr/bin/env python3
"""Administrative identity mapping CLI; no network calls and no account creation."""
import os
import sys
import accounts


def main():
    if os.geteuid() != 0:
        raise SystemExit('Administrative access required')
    args = sys.argv[1:]
    if args and args[0] == 'discord':
        args[0] = 'sso'  # Compatibility alias for the previous local prototype.
    if args == ['sso', 'list']:
        command = ['list']
    elif len(args) == 4 and args[:2] == ['sso', 'link']:
        command = ['link', '--user', args[2], '--discord-id', args[3]]
    elif len(args) == 3 and args[:2] == ['sso', 'unlink']:
        record = accounts.read_mapping().get(args[2])
        if not record:
            raise SystemExit('Discord ID is not linked')
        command = ['unlink', '--discord-id', args[2]]
    elif len(args) == 3 and args[:2] == ['sso', 'show']:
        command = ['show', '--discord-id' if args[2].isdigit() else '--user', args[2]]
    else:
        raise SystemExit('Usage: dci-servercontroller sso link USER DISCORD_ID | unlink DISCORD_ID | list | show DISCORD_ID_OR_USER')
    sys.argv = [sys.argv[0], *command]
    accounts.main()


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError) as error:
        raise SystemExit(str(error))

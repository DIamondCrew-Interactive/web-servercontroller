#!/usr/bin/env python3
"""Opt-in real PAM/bridge test; private sockets/maps, no production auth configuration edits.

Run as root on Debian 12 with Cockpit 287.1-0+deb12u3:
  python3 tests/debian_sso_integration.py --user skopy
Creates only temporary fixtures and normal PAM session/audit events for that user.
It does not exercise cockpit-ws cookies, browser login, sudo or production routing.
"""
import argparse
import json
import os
from pathlib import Path
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time

SOURCE = Path(__file__).resolve().parents[1] / 'sso'
SUBJECT = '584274123622973440'


def frame_write(pipe, value):
    payload = b'\n' + json.dumps(value).encode()
    pipe.write(str(len(payload)).encode() + b'\n' + payload)
    pipe.flush()


def frame_read(pipe, timeout=30):
    deadline = time.monotonic() + timeout
    def exact(size):
        data = b''
        while len(data) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([pipe], [], [], remaining)[0]:
                raise TimeoutError('Cockpit frame timeout')
            chunk = os.read(pipe.fileno(), size - len(data))
            if not chunk:
                raise ValueError('Unexpected Cockpit EOF')
            data += chunk
        return data
    line = b''
    while not line.endswith(b'\n'):
        line += exact(1)
        if len(line) > 16:
            raise ValueError('Oversized frame header')
    size = int(line)
    if not 1 <= size <= 1024 * 1024:
        raise ValueError('Oversized frame')
    channel, payload = exact(size).split(b'\n', 1)
    return channel.decode(), payload


def fixture(role, root, socket_path):
    """Test-only module overrides. Production binaries have no environment bypass."""
    sys.path.insert(0, str(root / 'source'))
    if role == 'broker':
        import pwd
        import socketserver
        import broker
        user = pwd.getpwnam('nobody')
        os.setgroups([])
        os.setresgid(user.pw_gid, user.pw_gid, user.pw_gid)
        os.setresuid(user.pw_uid, user.pw_uid, user.pw_uid)
        broker.Handler.store = broker.Store(root / 'broker' / 'grants.sqlite3')
        with socketserver.UnixStreamServer(str(socket_path), broker.Handler) as server:
            os.chmod(socket_path, 0o600)
            print('ready', flush=True)
            server.serve_forever()
    else:
        import accounts
        import auth
        accounts.MAPPING = root / 'mapping.json'
        auth.BROKER_SOCKET = str(socket_path)
        auth.BROKER_USER = 'nobody'
        def audit(event):
            with (root / 'pam-audit.jsonl').open('a') as output:
                output.write(json.dumps({'event':event, 'pid':os.getpid()}) + '\n')
        class ObservedPAM(auth.PAM):
            def __init__(self, username):
                super().__init__(username)
                audit('opened')
            def close(self):
                was_open = self.opened
                super().close()
                if was_open:
                    audit('closed')
        auth.PAM = ObservedPAM
        try:
            return auth.main()
        except Exception as error:
            print(type(error).__name__ + ': ' + str(error), file=sys.stderr)
            auth.send_frame({'command':'init', 'version':1, 'problem':'authentication-failed'})
            return 1


def stop(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


def run(username):
    if sys.platform != 'linux' or os.geteuid() != 0:
        raise ValueError('Requires root on Debian 12; no native test ran')
    import pwd
    release = dict(line.split('=',1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    if release.get('ID','').strip('"') != 'debian' or release.get('VERSION_ID','').strip('"') != '12':
        raise ValueError('Requires Debian 12')
    version = subprocess.check_output(['dpkg-query','-W','-f=${Version}','cockpit-ws'], text=True).strip()
    if version != '287.1-0+deb12u3' or not Path('/usr/bin/cockpit-bridge').is_file():
        raise ValueError('Requires Cockpit 287.1-0+deb12u3 and cockpit-bridge')
    sys.path.insert(0, str(SOURCE))
    import accounts
    from grants import Store
    user = pwd.getpwnam(username)
    if not accounts.eligible(user):
        raise ValueError('Choose an existing non-root interactive account')
    nobody = pwd.getpwnam('nobody')
    with tempfile.TemporaryDirectory(prefix='dci-pam-test-', dir='/var/tmp') as directory:
        root = Path(directory)
        os.chmod(root, 0o755)
        shutil.copytree(SOURCE, root/'source', ignore=shutil.ignore_patterns('__pycache__'))
        work = root/'broker'; work.mkdir(mode=0o700)
        os.chown(work, nobody.pw_uid, nobody.pw_gid)
        store = Store(work/'grants.sqlite3')
        os.chown(store.path, nobody.pw_uid, nobody.pw_gid)
        socket_path = work/'http.sock'
        command = [sys.executable, '-B', str(Path(__file__).resolve())]
        def mapping(uid=user.pw_uid, name=username):
            path = root/'mapping.json'
            path.write_text(json.dumps({SUBJECT:{'username':name,'uid':uid}}))
            path.chmod(0o600)
        mapping()
        broker = subprocess.Popen(command+['--fixture','broker',str(root),str(socket_path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        try:
            if not select.select([broker.stdout],[],[],15)[0] or broker.stdout.readline() != b'ready\n':
                raise ValueError('Private broker did not start')
            def session(ticket, expect_success):
                before = (root/'pam-audit.jsonl').read_text() if (root/'pam-audit.jsonl').exists() else ''
                process = subprocess.Popen(command+['--fixture','auth',str(root),str(socket_path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
                try:
                    channel, data = frame_read(process.stdout)
                    challenge = json.loads(data)
                    if channel or challenge.get('command') != 'authorize':
                        raise ValueError('Missing real auth conversation')
                    frame_write(process.stdin, {'command':'authorize','cookie':challenge['cookie'],'response':'Bearer '+ticket})
                    channel, data = frame_read(process.stdout)
                    init = json.loads(data)
                    if not expect_success:
                        if channel or init.get('problem') != 'authentication-failed':
                            raise ValueError('Invalid credentials unexpectedly accepted')
                        process.stdin.close(); process.wait(timeout=10)
                        after = (root/'pam-audit.jsonl').read_text() if (root/'pam-audit.jsonl').exists() else ''
                        if before != after or process.returncode == 0:
                            raise ValueError('Rejected login opened PAM session')
                        return
                    if channel or init.get('command') != 'init' or init.get('version') != 1 or init.get('problem'):
                        raise ValueError('Native PAM/bridge failed: '+json.dumps(init))
                    frame_write(process.stdin, {'command':'init','version':1,'host':'localhost'})
                    program = 'import os,json;print(json.dumps(dict(user=os.environ.get("USER"),uid=os.getuid(),uids=os.getresuid(),gids=os.getresgid(),groups=os.getgroups(),session=os.environ.get("XDG_SESSION_ID"))))'
                    frame_write(process.stdin, {'command':'open','channel':'identity','payload':'stream','spawn':['/usr/bin/python3','-c',program],'err':'message'})
                    output = b''
                    while True:
                        channel, data = frame_read(process.stdout)
                        if channel == 'identity': output += data
                        elif not channel:
                            control = json.loads(data)
                            if control.get('command') == 'close' and control.get('channel') == 'identity':
                                if control.get('problem') or control.get('exit-status',0) != 0:
                                    raise ValueError('Bridge spawn failed')
                                break
                    actual = json.loads(output)
                    expected_groups = set(os.getgrouplist(username, user.pw_gid))
                    if actual['user'] != username or actual['uid'] != user.pw_uid or actual['uids'] != [user.pw_uid]*3 or actual['gids'] != [user.pw_gid]*3 or set(actual['groups']) != expected_groups:
                        raise ValueError('Unix identity/groups mismatch')
                    process.stdin.close(); process.wait(timeout=15)
                    events = [json.loads(line)['event'] for line in (root/'pam-audit.jsonl').read_text()[len(before):].splitlines()]
                    if process.returncode != 0 or events != ['opened','closed']:
                        raise ValueError('PAM session did not close cleanly')
                    return actual
                finally:
                    stop(process)
                    for pipe in [process.stdin,process.stdout,process.stderr]: pipe.close()
            token = store.issue('bearer', SUBJECT, 30)
            actual = session(token, True)
            session(token, False)
            session(store.issue('bearer', SUBJECT, -1), False)
            session(store.issue('bearer', '317014531144679424', 30), False)
            mapping(uid=user.pw_uid+1)
            session(store.issue('bearer', SUBJECT, 30), False)
            mapping(uid=0, name='root')
            session(store.issue('bearer', SUBJECT, 30), False)
            print(json.dumps({'result':'PASS','cockpit':version,'native_identity':actual,'checks':['PAM open/close','real bridge spawn UID/GID/groups','replay','expiry','unmapped identity','UID mismatch','root denied'],'not_tested':['cockpit-ws cookie','browser','password fallback','sudo/polkit','Staff OAuth','production proxy']}, indent=2))
        finally:
            stop(broker)
            broker.stdout.close(); broker.stderr.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user')
    parser.add_argument('--fixture', nargs=3, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.fixture:
        sys.exit(fixture(args.fixture[0], Path(args.fixture[1]), Path(args.fixture[2])))
    if not args.user:
        parser.error('--user is required')
    run(args.user)

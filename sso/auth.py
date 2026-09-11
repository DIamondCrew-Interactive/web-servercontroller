#!/usr/bin/env python3
"""Root Cockpit bearer adapter: one-use Staff SSO ticket -> linked UID -> PAM session."""
import ctypes
from contextlib import closing
import http.client
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import struct
import sys

from accounts import linked_user

BROKER_SOCKET = "/run/dci-sso/http.sock"
BROKER_USER = "dci-sso"


def send_frame(value):
    payload = b'\n' + json.dumps(value).encode()
    sys.stdout.buffer.write(str(len(payload)).encode() + b'\n' + payload)
    sys.stdout.buffer.flush()


def read_frame():
    source = getattr(sys.stdin.buffer, 'raw', sys.stdin.buffer)
    line = source.readline(16)
    if not line.endswith(b'\n') or not line[:-1].isdigit():
        raise ValueError('Invalid protocol framing')
    size = int(line)
    if not 1 <= size <= 65536:
        raise ValueError('Invalid frame size')
    data = b''
    while len(data) < size:
        chunk = source.read(size - len(data))
        if not chunk:
            break
        data += chunk
    if len(data) != size or not data.startswith(b'\n'):
        raise ValueError('Invalid control frame')
    return json.loads(data[1:])


class LocalSSO(http.client.HTTPConnection):
    def connect(self):
        import pwd
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(10)
        self.sock.connect(BROKER_SOCKET)
        _, uid, _ = struct.unpack('3i', self.sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid != pwd.getpwnam(BROKER_USER).pw_uid:
            self.sock.close()
            raise ValueError('Unexpected Staff SSO broker identity')


class PAM:
    """Use Cockpit's account, credential and session policies after external authentication."""
    def __init__(self, username):
        class Message(ctypes.Structure):
            _fields_ = [('style', ctypes.c_int), ('message', ctypes.c_char_p)]
        class Response(ctypes.Structure):
            _fields_ = [('response', ctypes.c_char_p), ('code', ctypes.c_int)]
        callback = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.POINTER(Message)),
                                  ctypes.POINTER(ctypes.POINTER(Response)), ctypes.c_void_p)
        libc = ctypes.CDLL('libc.so.6')
        libc.calloc.argtypes = [ctypes.c_size_t, ctypes.c_size_t]
        libc.calloc.restype = ctypes.c_void_p
        def converse(count, messages, responses, context):
            if not 0 < count <= 32 or any(messages[i].contents.style not in (3, 4) for i in range(count)):
                return 19  # PAM_CONV_ERR; never silently approve an interactive challenge.
            allocated = libc.calloc(count, ctypes.sizeof(Response))
            if not allocated:
                return 5
            responses[0] = ctypes.cast(allocated, ctypes.POINTER(Response))
            return 0
        class Conversation(ctypes.Structure):
            _fields_ = [('function', callback), ('context', ctypes.c_void_p)]
        self.callback = callback(converse)
        self.conversation = Conversation(self.callback, None)
        self.lib = ctypes.CDLL('libpam.so.0')
        self.handle = ctypes.c_void_p()
        self.lib.pam_start.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.POINTER(Conversation), ctypes.POINTER(ctypes.c_void_p)]
        self.lib.pam_set_item.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        for name in ['pam_acct_mgmt', 'pam_setcred', 'pam_open_session', 'pam_close_session', 'pam_end']:
            getattr(self.lib, name).argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.lib.pam_getenv.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        self.lib.pam_getenv.restype = ctypes.c_char_p
        self.lib.pam_putenv.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
        self.opened = self.credentials = False
        self.check(self.lib.pam_start(b'cockpit', username.encode(), ctypes.byref(self.conversation), ctypes.byref(self.handle)))
        try:
            self.check(self.lib.pam_set_item(self.handle, 3, ctypes.c_char_p(b'cockpit')))
            self.check(self.lib.pam_set_item(self.handle, 4, ctypes.c_char_p(b'staff-sso')))
            import pwd
            account = pwd.getpwnam(username)
            for value in [b'XDG_SESSION_CLASS=user', b'XDG_SESSION_TYPE=web', ('HOME=' + account.pw_dir).encode()]:
                self.check(self.lib.pam_putenv(self.handle, value))
            self.check(self.lib.pam_acct_mgmt(self.handle, 0))
            self.check(self.lib.pam_setcred(self.handle, 2))
            self.credentials = True
            self.check(self.lib.pam_open_session(self.handle, 0))
            self.opened = True
            self.check(self.lib.pam_setcred(self.handle, 8))  # PAM_REINITIALIZE_CRED
            self.lib.pam_get_item.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
            pam_user = ctypes.c_void_p()
            self.check(self.lib.pam_get_item(self.handle, 2, ctypes.byref(pam_user)))
            if ctypes.cast(pam_user, ctypes.c_char_p).value != username.encode():
                raise ValueError('PAM changed the explicitly mapped identity')
        except BaseException:
            self.close()
            raise

    @staticmethod
    def check(result):
        if result:
            raise ValueError('PAM policy denied the session')

    def environment(self):
        result = {}
        for key in ['XDG_RUNTIME_DIR', 'XDG_SESSION_ID', 'XDG_SESSION_CLASS', 'XDG_SESSION_TYPE', 'DBUS_SESSION_BUS_ADDRESS']:
            value = self.lib.pam_getenv(self.handle, key.encode())
            if value:
                result[key] = value.decode()
        return result

    def close(self):
        errors = []
        if self.opened:
            errors.append(self.lib.pam_close_session(self.handle, 0))
            self.opened = False
        if self.credentials:
            errors.append(self.lib.pam_setcred(self.handle, 4))
            self.credentials = False
        if self.handle:
            errors.append(self.lib.pam_end(self.handle, next((code for code in errors if code), 0)))
            self.handle = ctypes.c_void_p()
        if any(errors):
            raise ValueError('PAM session cleanup failed')


def main():
    if os.geteuid() != 0:
        raise ValueError('Root socket service required')
    cookie = secrets.token_urlsafe(24)
    send_frame({'command': 'authorize', 'cookie': cookie, 'challenge': '*'})
    frame = read_frame()
    if frame.get('command') != 'authorize' or frame.get('cookie') != cookie:
        raise ValueError('Unexpected authorization response')
    scheme, ticket = frame.get('response', '').split(' ', 1)
    if scheme.lower() != 'bearer' or len(ticket) != 43:
        raise ValueError('Unsupported credentials')
    with closing(LocalSSO('localhost')) as connection:
        connection.request('POST', '/internal/consume', json.dumps({'ticket': ticket}), {'Content-Type': 'application/json'})
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError('Expired or invalid ticket')
        identity = json.loads(response.read(4096))['discord_id']
    account = linked_user(identity)  # Re-check root-owned mapping at every login.
    if account.pw_shell not in Path('/etc/shells').read_text().splitlines() or not os.access(account.pw_shell, os.X_OK):
        raise ValueError('Invalid login shell')
    with open('/etc/shadow', encoding='utf-8') as shadow:
        entry = next((line.split(':') for line in shadow if line.split(':', 1)[0] == account.pw_name), None)
    if not entry or not entry[1] or entry[1].startswith(('!', '*')):
        raise ValueError('Locked or passwordless Unix account')
    pam = PAM(account.pw_name)
    try:
        current = linked_user(identity)
        if (current.pw_name, current.pw_uid, current.pw_gid) != (account.pw_name, account.pw_uid, account.pw_gid):
            raise ValueError('Mapped identity changed during session setup')
        environment = {'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
                       'HOME': account.pw_dir, 'USER': account.pw_name, 'LOGNAME': account.pw_name,
                       'SHELL': account.pw_shell, 'LANG': 'C.UTF-8', **pam.environment()}
        child = os.fork()
        if child == 0:
            try:
                os.initgroups(account.pw_name, account.pw_gid)
                os.setresgid(account.pw_gid, account.pw_gid, account.pw_gid)
                os.setresuid(account.pw_uid, account.pw_uid, account.pw_uid)
                if os.getresuid() != (account.pw_uid,) * 3 or os.getresgid() != (account.pw_gid,) * 3:
                    os._exit(1)
                os.closerange(3, os.sysconf('SC_OPEN_MAX'))
                os.chdir(account.pw_dir)
                os.execve('/usr/bin/cockpit-bridge', ['cockpit-bridge'], environment)
            except BaseException:
                os._exit(1)
        def forward(signum, _frame):
            try:
                os.kill(child, signum)
            except ProcessLookupError:
                pass
        for signum in [signal.SIGTERM, signal.SIGINT, signal.SIGQUIT]:
            signal.signal(signum, forward)
        _, status = os.waitpid(child, 0)
        return os.waitstatus_to_exitcode(status)
    finally:
        pam.close()


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        send_frame({'command': 'init', 'version': 1, 'problem': 'authentication-failed'})
        sys.exit(1)

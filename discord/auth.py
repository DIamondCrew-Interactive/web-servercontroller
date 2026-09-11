#!/usr/bin/env python3
"""Root Cockpit bearer adapter: one-use OAuth ticket -> linked UID -> PAM session."""
import ctypes
from contextlib import closing
import http.client
import json
import os
import secrets
import socket
import struct
import sys

from accounts import linked_user


def send_frame(value):
    payload = b'\n' + json.dumps(value).encode()
    sys.stdout.buffer.write(str(len(payload)).encode() + b'\n' + payload)
    sys.stdout.buffer.flush()


def read_frame():
    line = sys.stdin.buffer.readline(16)
    if not line.endswith(b'\n') or not line[:-1].isdigit():
        raise ValueError('Invalid protocol framing')
    size = int(line)
    if not 1 <= size <= 65536:
        raise ValueError('Invalid frame size')
    data = sys.stdin.buffer.read(size)
    if len(data) != size or not data.startswith(b'\n'):
        raise ValueError('Invalid control frame')
    return json.loads(data[1:])


class LocalOAuth(http.client.HTTPConnection):
    def connect(self):
        import pwd
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(10)
        self.sock.connect('/run/dci-discord/http.sock')
        _, uid, _ = struct.unpack('3i', self.sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid != pwd.getpwnam('dci-discord').pw_uid:
            self.sock.close()
            raise ValueError('Unexpected OAuth broker identity')


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
        self.opened = self.credentials = False
        self.check(self.lib.pam_start(b'cockpit', username.encode(), ctypes.byref(self.conversation), ctypes.byref(self.handle)))
        try:
            self.check(self.lib.pam_set_item(self.handle, 3, ctypes.c_char_p(b'cockpit')))
            self.check(self.lib.pam_set_item(self.handle, 4, ctypes.c_char_p(b'discord-oauth')))
            self.check(self.lib.pam_acct_mgmt(self.handle, 0))
            self.check(self.lib.pam_setcred(self.handle, 2))
            self.credentials = True
            self.check(self.lib.pam_open_session(self.handle, 0))
            self.opened = True
        except BaseException:
            self.close()
            raise

    @staticmethod
    def check(result):
        if result:
            raise ValueError('PAM policy denied the session')

    def environment(self):
        result = {}
        for key in ['XDG_RUNTIME_DIR', 'DBUS_SESSION_BUS_ADDRESS']:
            value = self.lib.pam_getenv(self.handle, key.encode())
            if value:
                result[key] = value.decode()
        return result

    def close(self):
        if self.opened:
            self.lib.pam_close_session(self.handle, 0)
        if self.credentials:
            self.lib.pam_setcred(self.handle, 4)
        if self.handle:
            self.lib.pam_end(self.handle, 0)
            self.handle = ctypes.c_void_p()


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
    with closing(LocalOAuth('localhost')) as connection:
        connection.request('POST', '/internal/consume', json.dumps({'ticket': ticket}), {'Content-Type': 'application/json'})
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError('Expired or invalid ticket')
        identity = json.loads(response.read(4096))['discord_id']
    account = linked_user(identity)  # Re-check root-owned mapping at every login.
    with open('/etc/shadow', encoding='utf-8') as shadow:
        entry = next((line.split(':') for line in shadow if line.split(':', 1)[0] == account.pw_name), None)
    if not entry or not entry[1] or entry[1].startswith(('!', '*')):
        raise ValueError('Locked or passwordless Unix account')
    pam = PAM(account.pw_name)
    try:
        environment = {'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
                       'HOME': account.pw_dir, 'USER': account.pw_name, 'LOGNAME': account.pw_name,
                       'SHELL': account.pw_shell, 'LANG': 'C.UTF-8', **pam.environment()}
        child = os.fork()
        if child == 0:
            try:
                os.initgroups(account.pw_name, account.pw_gid)
                os.setgid(account.pw_gid)
                os.setuid(account.pw_uid)
                os.chdir(account.pw_dir)
                os.execve('/usr/bin/cockpit-bridge', ['cockpit-bridge'], environment)
            except BaseException:
                os._exit(1)
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

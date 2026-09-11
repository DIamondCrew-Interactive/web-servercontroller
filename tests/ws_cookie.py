"""Optional real cockpit-ws HTTP cookie gate for the isolated Debian harness.

No production socket/config edits, no browser credentials, no public listener.
Upstream 287.1: src/ws/main.c (LISTEN_FDS), src/common/cockpitconf.c
(XDG_CONFIG_DIRS), src/ws/cockpitauth.c ([bearer] UnixPath and session cookies).
"""
from contextlib import closing
import base64
import http.client
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import socket
import socketserver
import subprocess
import threading
import time
from urllib.parse import quote

# Debian 287.1 cockpit-wsinstance service identity, distinct from cockpit-tls.
WS_ACCOUNT = "cockpit-wsinstance"


def response_shape(value):
    """Diagnostics contain field names only, never session credential values."""
    if not isinstance(value, dict):
        return {'json_type':type(value).__name__}
    result = {'keys':sorted(str(key)[:80] for key in value)}
    if isinstance(value.get('login-data'), dict):
        result['login_data_keys'] = sorted(str(key)[:80] for key in value['login-data'])
    return result


def login_payload(status, body):
    # 287.1 cockpit_creds_to_json() has csrf-token and optional login-data.
    # It does not expose a top-level user, and login-data is not mandatory.
    try:
        value = json.loads(body)
    except ValueError:
        raise ValueError('Cockpit login returned non-JSON; status='+str(status)) from None
    if status != 200 or not isinstance(value, dict) or not isinstance(value.get('csrf-token'), str) or not value['csrf-token']:
        raise ValueError('Invalid Cockpit login response: '+json.dumps({'status':status, **response_shape(value)}))
    return value


def ws_binary():
    for path in ['/usr/lib/cockpit/cockpit-ws', '/usr/libexec/cockpit-ws']:
        if Path(path).is_file() and os.access(path, os.X_OK):
            return path
    raise ValueError('Native cockpit-ws binary not found')


def exec_ws(root, descriptor):
    import pwd
    account = pwd.getpwnam(WS_ACCOUNT)
    os.dup2(descriptor, 3, inheritable=True)
    if descriptor != 3:
        os.close(descriptor)
    os.setgroups([])
    os.setresgid(account.pw_gid, account.pw_gid, account.pw_gid)
    os.setresuid(account.pw_uid, account.pw_uid, account.pw_uid)
    environment = {'PATH':'/usr/bin:/bin', 'LANG':'C.UTF-8',
                   'HOME':str(root/'ws-runtime'), 'XDG_RUNTIME_DIR':str(root/'ws-runtime'),
                   'XDG_CONFIG_DIRS':str(root/'ws-config'),
                   'LISTEN_PID':str(os.getpid()), 'LISTEN_FDS':'1'}
    binary = ws_binary()
    os.execve(binary, [binary, '--no-tls', '--address=127.0.0.1'], environment)


def run(root, store, user, command, broker_socket, stop):
    import pwd
    account = pwd.getpwnam(WS_ACCOUNT)
    ws_binary()
    config = root/'ws-config'/'cockpit'
    config.mkdir(parents=True)
    runtime = root/'ws-runtime'; runtime.mkdir(mode=0o700)
    os.chown(runtime, account.pw_uid, account.pw_gid)
    auth_socket = root/'ws-auth.sock'
    # Disable other methods only in this private fixture: never reach the real
    # password auth socket or ask the operator for Linux credentials.
    (config/'cockpit.conf').write_text(
        '[WebService]\nAllowUnencrypted = true\n'
        '[bearer]\nUnixPath = '+str(auth_socket)+'\n'
        '[basic]\naction = none\n[negotiate]\naction = none\n[tls-cert]\naction = none\n')
    processes = []
    errors = []
    lock = threading.Lock()
    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            try:
                process = subprocess.Popen(command+['--fixture','auth',str(root),str(broker_socket)],
                    stdin=self.request, stdout=self.request, stderr=subprocess.DEVNULL, start_new_session=True)
                with lock: processes.append(process)
                process.wait(timeout=60)
            except Exception as error:
                with lock: errors.append(type(error).__name__)
    class Server(socketserver.ThreadingUnixStreamServer):
        daemon_threads = True
        block_on_close = False
    server = Server(str(auth_socket), Handler)
    os.chown(auth_socket, 0, account.pw_gid); os.chmod(auth_socket, 0o660)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    audit = root/'pam-audit.jsonl'
    before = audit.read_text() if audit.exists() else ''
    ws = None
    def request(port, headers=None, path='/cockpit/login'):
        with closing(http.client.HTTPConnection('127.0.0.1',port,timeout=15)) as client:
            client.request('GET',path,headers=headers or {})
            response=client.getresponse()
            return response.status,response.getheaders(),response.read(65536)
    try:
        with closing(socket.socket(socket.AF_INET,socket.SOCK_STREAM)) as listener:
            listener.bind(('127.0.0.1',0)); listener.listen(16)
            port = listener.getsockname()[1]
            ws = subprocess.Popen(command+['--fixture','ws',str(root),str(listener.fileno())],
                pass_fds=(listener.fileno(),), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True)
        deadline=time.monotonic()+15
        while True:
            if ws.poll() is not None: raise ValueError('Private cockpit-ws exited before readiness')
            try:
                if request(port,path='/ping')[0]==200: break
            except (OSError,http.client.HTTPException): pass
            if time.monotonic()>deadline: raise TimeoutError('Private cockpit-ws readiness failed')
            time.sleep(0.1)
        token=store.issue('bearer','584274123622973440',30)
        status,headers,body=request(port,{'Authorization':'Bearer '+token,'X-Superuser':'none'})
        login = login_payload(status, body)
        cookies=SimpleCookie()
        for name,value in headers:
            if name.lower()=='set-cookie': cookies.load(value)
        if 'cockpit' not in cookies or not cookies['cockpit'].value or not cookies['cockpit']['httponly'] or cookies['cockpit']['samesite'].lower()!='strict':
            raise ValueError('Missing genuine protected Cockpit session cookie')
        # The next request has ONLY the ws-issued cookie: no bearer or Linux password.
        status,_,body=request(port,{'Cookie':'cockpit='+cookies['cockpit'].value})
        again = login_payload(status, body)
        if again['csrf-token'] != login['csrf-token']:
            raise ValueError('Cockpit cookie-only request did not retain its session')
        # Read identity through the SAME ws-authenticated session. The external
        # channel endpoint checks both the cookie and the session CSRF token.
        # No command/channel fields: upstream assigns those to external channels.
        program = 'import os,json;print(json.dumps(dict(user=os.environ.get("USER"),uids=os.getresuid(),gids=os.getresgid(),groups=os.getgroups())))'
        options = {'payload':'stream','spawn':['/usr/bin/python3','-c',program],
                   'err':'message','superuser':False,'external':{'content-type':'application/json'}}
        channel_path = '/cockpit/channel/'+quote(login['csrf-token'],safe='')+'?'+base64.b64encode(json.dumps(options).encode()).decode()
        status,_,body=request(port,{'Cookie':'cockpit='+cookies['cockpit'].value},path=channel_path)
        try:
            identity=json.loads(body)
        except ValueError:
            raise ValueError('Cookie-authenticated identity channel returned non-JSON; status='+str(status)) from None
        if status!=200 or not isinstance(identity,dict) or identity.get('user')!=user.pw_name or identity.get('uids')!=[user.pw_uid]*3 or identity.get('gids')!=[user.pw_gid]*3 or set(identity.get('groups',[]))!=set(os.getgrouplist(user.pw_name,user.pw_gid)):
            safe_identity={key:identity.get(key) for key in ['user','uids','gids','groups']} if isinstance(identity,dict) else {}
            raise ValueError('Cookie session Unix identity mismatch: '+json.dumps({'status':status,'identity':safe_identity,**response_shape(identity)}))
        for headers in [{}, {'Cookie':'cockpit=invalid'}, {'Authorization':'Bearer '+token,'X-Superuser':'none'}]:
            if request(port,headers)[0]!=401:
                raise ValueError('Anonymous/tampered-cookie/replayed-bearer request accepted')
        stop(ws)
        with lock: pending=list(processes)
        for process in pending: process.wait(timeout=15)
        events=[json.loads(line)['event'] for line in audit.read_text()[len(before):].splitlines()]
        if events!=['opened','closed'] or errors:
            raise ValueError('Private ws session did not complete PAM cleanup')
        return {'result':'PASS','user':user.pw_name,'uid':user.pw_uid,'native_identity':identity,
                'checks':['Bearer HTTP login','real cockpit cookie','cookie-only authenticated request',
                          'same-cookie native bridge UID/GID/groups',
                          'anonymous refused','tampered cookie refused','bearer replay refused','PAM cleanup'],
                'transport':'HTTP on private ephemeral 127.0.0.1 listener; not production TLS/browser'}
    finally:
        if ws is not None: stop(ws)
        server.shutdown(); server.server_close(); thread.join(timeout=5)
        with lock: pending=list(processes)
        for process in pending: stop(process)

# Server Controller 1.2.2 verification

- Current Windows run: 60 Python tests collected, 56 PASS, 4 POSIX-only skipped.
- Previous unchanged frontend: 32 browser assertions PASS.
- Signed Staff/Controller joint HTTP test PASS: existing Staff OAuth/session
  fixture, issuance/redeem, Ed25519 validation, canonical identity preservation,
  one-use local bearer and callback replay refusal. Discord API and HTTPS
  transport are mocked only in this joint fixture.
- Signature/key/algorithm/audience/issuer/state/subject/time checks, durable
  concurrent replay protection, CLI, installer/lifecycle and source packaging
  tests PASS. Installer unit tests simulate system commands.
- Actual Cockpit 287.1 login JSON schema and diagnostic redaction tests PASS.

## Confirmed native DIA results

The main deployment integrator ran candidate
8774e78d25215de47113d17cd301f2b1446c2c6b from archive
1aab1ed42afd04f13074c62abd5a8d8bc8f2cb866e94b0f733dfa6f38c0caa71:

`sudo python3 -B tests/debian_sso_integration.py --user skopy --with-ws`

Result: PASS, reported as INTEGRATION_PASS controller. Cockpit was
287.1-0+deb12u3 on Debian 12; actual skopy UID/GID 1001 and groups [27,100,1001].

Confirmed: real PAM open/close and credential cleanup; original cockpit-bridge
real/effective/saved UID/GID and groups; rejected replay, expired bearer,
unmapped Discord ID, changed pinned UID and root mapping; real cockpit-ws HTTP
bearer login; ws-issued HttpOnly/SameSiteStrict cookie; cookie-only session
continuity; same-cookie authenticated channel executing identity reporting
under the mapped Unix user; anonymous/tampered-cookie/replayed-bearer refusal;
PAM cleanup after stopping the private ws. Temporary resources were cleaned up.

The cookie test uses Cockpit 287.1's actual csrf-token plus optional login-data
schema, not a nonexistent top-level user. Identity is verified through the
same session's authenticated external stream channel. Runtime authentication
was unchanged between the native-tested candidate and final documentation prep.

## Remaining boundaries

Native tests use temporary config/runtime/Unix sockets and an ephemeral
127.0.0.1 HTTP listener. They do not change production auth configuration.
Real Discord login through the production browser/HTTPS/proxy, actual password
fallback login and sudo/polkit end-to-end remain unverified. Browser assertions
use static fixtures and mocked SSO responses. Sudo rules are unchanged; SSO does
not promise passwordless privilege elevation or grant extra Unix rights.

Source archives are built from an explicit allowlist, verified against
MANIFEST.sha256, checked for known credential patterns and byte-reproducibility.
This is not a guarantee of detecting every possible form of sensitive data.

## 1.2.1 installer regression gate

The 1.2.0 production installer attempt under root umask 077 failed because its
managed /usr/local/lib/dci-sso directory became 0700; broker.py itself was 0644.
All parent directories were 0755. Rollback removed SSO and restored theme 1.1.0;
the integrator separately restored cockpit.conf mode 0644 with unchanged content.

1.2.1 explicitly applies intended modes after creation, repairs its own empty
0700 target directory, and saves original cockpit.conf existence/mode/UID/GID
for rollback. Existing unrelated parent modes are not broadened. Legacy state
without saved metadata preserves the observed mode; it cannot infer history.
Auth/broker/PAM/Unix mapping logic is unchanged from native-tested 1.2.0.

Run the installer-only gate as root on Debian BEFORE another production install:

```sh
(umask 077; python3 -m unittest discover -s tests -p test_sso_install.py -v)
```

This uses only temporary files and mocks system/user/service commands. Its real
POSIX checks exercise new nested parents, retained empty 0700 target repair,
0640/0644 config round trips, restoration after mode drift, unsafe parent refusal,
and an unprivileged child reading/compiling installed broker sources. The three
POSIX-specific tests were skipped on Windows; native result is still pending.
This test does not start the production service or install an adapter.

## 1.2.2 production web-instance identity fix

Production evidence: the HTTPS cockpit-wsinstance unit reported permission denied
connecting to /run/dci-sso-auth.sock, and no dci-sso-auth instance started. Its
actual systemd properties were User=Group=cockpit-wsinstance, DynamicUser=no,
PrivateUsers=no, with no supplementary groups or inaccessible paths. The socket
incorrectly used root:cockpit-ws 0660. cockpit-ws is the TLS frontend identity,
not the HTTP/HTTPS web instance identity in Debian 287.1-0+deb12u3.

The fix changes only SocketGroup to cockpit-wsinstance and the installer group
preflight. The isolated native ws fixture now uses cockpit-wsinstance too. It
keeps socket mode 0660 and does not add users, global group memberships, or
world access. PAM, sudo and identity/token verification logic are unchanged.

A new regression reads the checksum-pinned cockpit-ws Debian package and
compares BOTH HTTP and HTTPS systemd User/Group with our SocketGroup and test
fixture identity. It passed locally with the pinned package present. An installer
regression refuses a missing cockpit-wsinstance group before changing anything.

The previous isolated native PASS did not cover this production group boundary,
as its fixture ran ws under cockpit-ws. The main integrator confirmed CONTROLLER_122_NATIVE_RETRY_PASS on DIA for
1.2.2 candidate 003bed057d87b69effc55e18130f095d3a653566 with umask 022. This
used the actual cockpit-wsinstance identity and passed PAM plus native cookie
checks. Production browser login remains pending.
The real Staff session and Controller redemption had succeeded before the
production Cockpit connection failure.

### Native fixture umask correction

The first 1.2.2 native attempt under umask 077 returned HTTP 401 because the
TEST fixture's ws-config/cockpit directories and cockpit.conf were root-only.
The same exact candidate passed when the integrator reran it under umask 022,
confirming that the production socket group fix was independent of this test bug.

The final fixture explicitly applies 0755 to its public config directories and
0644 to its non-secret cockpit.conf, and checks readability after dropping to
the actual wsinstance identity. Mapping, broker data and private runtime remain
private. Regression tests include an actual POSIX umask 077 test and a root child
reading the file as cockpit-wsinstance when that account exists. The final
fixture must be rerun under umask 077 before release; production code is unchanged.

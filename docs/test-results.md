# Server Controller 1.2.0 verification

- 51 Python tests PASS; 32 browser assertions PASS.
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

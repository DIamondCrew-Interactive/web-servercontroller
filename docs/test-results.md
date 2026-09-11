# Verification of working 1.2.0: signed Staff assertions

- 48 Server Controller Python tests PASS; 32 browser assertions PASS.
- Ed25519 signature/key/payload tampering, algorithm and local kid pinning,
  rejected jwk/jku, duplicate/extra JSON members, issuer/audience/state/subject,
  UUIDv4 jti and integer time/TTL/skew/expiry boundaries covered.
- Durable SQLite replay cache accepts exactly once under concurrency and rejects
  after reopening the database. Invalid signatures do not populate replay cache.
- Callback cookie binding, CSRF, one-use handles/bearers and fallback UI covered.
- CLI sso link/unlink/list/show dispatch, root requirement, filtered show covered.
- PAM cleanup unit test checks all cleanup phases run even after a close error.
- Build/lifecycle and reproducible source archive/MANIFEST tests PASS.
  Installer tests use temporary files and simulated Debian commands.

Signed Staff/SC HTTP integration PASS against the main integrator's work/web-staff
checkout: Staff OAuth/session fixture -> signed issuance/redeem -> Controller
Ed25519 verification -> one-use local bearer; canonical ID preserved and callback
replay rejected. Issuer is read from fixture metadata and pinned by Staff to
https://staff.diamondcrew.net. Discord API and HTTPS transport are mocked only
in the integration fixture. No native PAM/session was executed by this test.

The native tests/debian_sso_integration.py harness is prepared and syntax checked.
Windows cannot execute native Linux PAM/bridge; native PASS is not claimed.
It uses an existing account and temporary socket/map/DB, checks actual PAM
open/close and bridge UID/GID/groups, and refuses replay/expiry/unmapped/UID/root.
See sso-verification.md for requirements and expected audit/session effects.

Browser checks use static fixtures and mocked SSO responses. Actual cockpit-ws
cookie/session lifecycle, sudo/polkit, password login, Staff OAuth and production
routing still need staging verification. Nothing was pushed or deployed.

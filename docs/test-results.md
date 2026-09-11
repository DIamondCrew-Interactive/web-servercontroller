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

The main integrator reported native DIA PASS for exact candidate 9ddb205 and
archive fae91edc674ee488b917bef12ee80d2b18d5c814d938002d36188dbee99d3d44:
Cockpit 287.1-0+deb12u3, actual skopy UID/GID 1001, groups [27,100,1001],
PAM open/close, real bridge and replay/expiry/unmapped/UID/root negatives PASS.
This Windows task did not itself execute that native test.

The additional --with-ws mode is prepared and syntax checked, but still needs
native execution against the new candidate. It verifies genuine cockpit-ws
cookie issuance/use on an isolated loopback listener, with private config,
runtime/auth sockets, and PAM cleanup. See sso-verification.md for boundaries.

Browser checks use static fixtures and mocked SSO responses. Actual cockpit-ws
cookie gate, sudo/polkit, password login, Staff OAuth and production routing still
need further verification. Only the integration candidate branch is published;
main/tag/release/production were not changed by this task.

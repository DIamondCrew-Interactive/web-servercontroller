# DiamondCrew Interactive / Server Controller 1.2.2

Fix real Debian cockpit-wsinstance access to the custom bearer socket. Debian
287.1 runs cockpit-tls as cockpit-ws, but the HTTPS/HTTP web instances as
cockpit-wsinstance. The socket now uses root:cockpit-wsinstance 0660; no global
group membership changes or world-accessible permissions are introduced.

The installer checks the correct group, and the native cookie fixture now runs
under the actual web-instance identity. A checksum-pinned Debian systemd-unit
regression prevents confusing these two service identities again.

Retains the 1.2.1 restrictive-umask and configuration-mode rollback fixes.
PAM, sudo rules, Staff ticket verification and Unix mapping are unchanged.
See docs/test-results.md for the production failure evidence and remaining tests.

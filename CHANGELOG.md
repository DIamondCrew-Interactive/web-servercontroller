# 1.2.2

- Grant the bearer auth socket to Debian's actual cockpit-wsinstance group,
  not cockpit-ws (the separate TLS frontend identity). Keep mode 0660.
- Require the correct group during installation and use the same production
  service identity in the isolated native cookie test.
- Add a regression against checksum-pinned Debian systemd unit definitions.
- PAM, sudo, OAuth verification and Unix mapping behavior remain unchanged.

# 1.2.1

- Fix opt-in SSO installation under restrictive root umask 077: explicit runtime
  directory and file permissions, preserving private configuration permissions.
- Preserve original cockpit.conf mode across install/uninstall instead of
  deriving rollback permissions from a potentially modified managed file.
- Runtime Staff ticket verification, Cockpit bearer/PAM and Unix mapping unchanged.

# 1.2.0

- Staff Center is the only Discord OAuth provider. Replace independent OAuth
  with audience-bound, browser-bound, one-use Staff SSO ticket redemption.
- Keep local Unix identity mapping, password fallback and separate opt-in auth
  lifecycle. Add mapping CLI and cross-repository HTTP contract test.
- Native PAM/bridge and real cockpit-ws cookie identity gates passed on Debian 12.

# 1.1.0

- Centered login card matching the supplied reference; logo inside the card,
  readable fields/password toggle in light mode, no white server-details strip.
- Create. Play. Together. tagline and targeted Czech translation corrections.
- Optional Discord authorization-code broker, single-use login tickets, existing
  UID mapping, administrative account-link UI and Cockpit bearer/PAM adapter.
- Separate opt-in Discord installation; no server credentials in source.
- Requires Debian integration validation before enabling Discord authentication.

# 1.0.0

- Initial DiamondCrew Interactive / Server Controller theme for Debian 12,
  Cockpit 287.1-0+deb12u3.
- Shared dark navy theme, supplied logo, blue/pink/gold accents, login branding,
  shell brand block and 14 generated HTML entry-point overrides.
- Guarded install/update, original-Cockpit uninstall, previous-generation rollback,
  APT fallback, deterministic source packaging and offline visual fixtures.
- Backend integration is pending validation on a disposable Debian host.
- Release CI downloads checksum-pinned public Debian assets, runs tests/build,
  and publishes the verified source archive plus SHA256SUMS for version tags.

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

# Lokální ověření 1.1.0

Windows, Python 3.13, Node 22, Playwright/Chrome. **29 Python testů a 32 browser assertions PASS.** Python syntax a GitHub workflow actionlint prošly.

- Build nad veřejnými Debian balíčky Cockpit 287.1-0+deb12u3: 14 HTML vstupů, 3 upravené české katalogy. Původní aplikační kód a manifesty zachovány.
- Lifecycle simulace: dvě dpkg diversions, install/update/rollback/uninstall, APT fallback, odmítnutí změněného upstreamu včetně login HTML.
- OAuth: jednorázové a expirované tikety, vazba state na cookie, callback, redeem, kontrola Origin, duplicitní parametry, konfigurace HTTPS, UID mapování a rámování Cockpit protokolu.
- Browser: desktop/mobile login, odstranění bílého pruhu, čitelné popisky, vypnutý Discord bez konfigurace, skrytí OAuth při PAM výzvě, přidání/odebrání Discord ID s požadavkem superuser. Dále kontroly modulových stylů, dialogů a focusu.
- Source archiv: allowlist, reprodukovatelnost a manifest hashů kontroluje Python test.

Browser používá původní CSS a upravený login markup, ale autentizační upstream JS je ve statickém náhledu odstraněn. Discord odpovědi a Cockpit spawn jsou mockované. Lifecycle simuluje systémové příkazy; OAuth HTTP testy používají lokální test server a mock Discord identity.

Skutečný Cockpit backend, Linux PAM/systemd, Discord aplikace, reverse proxy, živé moduly a oprávnění po OAuth přihlášení nebyly lokálně ověřeny. Test success nenahrazuje Debian integrační ověření podle discord.md a debian-validation.md.

Tento záznam popisuje ověření před publikací 1.1.0. Výsledek release CI je dostupný v GitHub Actions. Původní 1.0.0 byla na DIA-01 ověřena instalací a HTTP kontrolami; to neověřuje novou autentizaci v 1.1.0.

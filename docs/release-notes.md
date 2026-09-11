# DiamondCrew Interactive / Server Controller 1.2.0

Centrální Staff SSO nahrazuje samostatný Discord OAuth. Login tlačítko:
Pokračovat přes DiamondCrew Interactive. Heslový Cockpit login zůstává.
Staff session vydává audience-bound 45sekundové jednorázové tikety. Server
Controller ověří server-to-server redeem, Ed25519 assertion, browser binding,
jednorázovost a vlastní Unix mapping se skutečným UID.

Vyžaduje odpovídající Staff změny a konfiguraci podle docs/sso.md. Samotný
theme update SSO nespouští. Nativní Debian PAM/bridge a cockpit-ws cookie včetně
Unix identity stejné session prošly izolovaným testem na DIA. Reálný Discord
browser login, heslový fallback a sudo/polkit E2E zůstávají neověřené.
Sudo pravidla se nemění. Podrobné výsledky: docs/test-results.md.

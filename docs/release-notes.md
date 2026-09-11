# DiamondCrew Interactive / Server Controller 1.2.0 — pracovní source

Centrální Staff SSO nahrazuje samostatný Discord OAuth. Login tlačítko:
Pokračovat přes DiamondCrew Interactive. Heslový Cockpit login zůstává.
Staff session vydává audience-bound 45sekundové jednorázové tikety. Server
Controller ověří server-to-server redeem, browser binding a vlastní Unix mapping.

Vyžaduje odpovídající Staff změny a konfiguraci podle docs/sso.md. Samotný
theme update SSO nespouští. Native Debian PAM/session integrace není lokálně
ověřená; před produkcí provést staging test. Nic nebylo pushnuto ani nasazeno.
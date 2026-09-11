# DiamondCrew Interactive / Server Controller

Pracovní source **1.2.0** pro Debian 12 a Cockpit **287.1-0+deb12u3**.
Produkční release 1.1.0 se nepřepisuje. Tyto změny nejsou pushnuté ani nasazené.

## Centrální Staff SSO

Staff Center je jediný Discord OAuth provider. Login nabízí **Pokračovat přes
DiamondCrew Interactive** nebo původní Linux username/password. Server Controller
zpracuje krátkodobý jednorázový Staff ticket a explicitní lokální mapování Discord
ID na existující Unix účet. Nemá Discord Client ID/Secret ani přímé Discord API
volání. Samostatný experimentální Discord OAuth byl ze source odstraněn.

Kompletní architektura, konfigurace, testy, deployment pořadí a rollback:
[docs/sso.md](docs/sso.md). Staff část je v samostatném lokálním checkoutu
`../staff-center-sso` repozitáře https://github.com/DIamondCrew-Interactive/web-staff.

**SSO/PAM backend není zatím ověřený na skutečném Debianu.** Lokální HTTP testy
a testy protokolu nenahrazují kontrolu Unix relace, oprávnění a sudo/polkit.
Instalace theme ho automaticky neaktivuje.

## Theme

Navy vzhled, původní logo, gradient #2ec7ff → #f43cb2 → #f3d36b, centrální login
karta a Create. Play. Together. Generátor překrývá osm původních Cockpit modulů,
přidává CSS do 14 HTML vstupů a opravuje cílené české katalogy. Upstream aplikační
JavaScript a manifesty zachovává. Login HTML a Debian branding.css mají dva
evidované dpkg diversions. Ostatní moduly, PAM heslový login a Cockpit API zůstávají.

`dci_discord` je zachovaný název balíčku pro lokální správu mapování, aby update
z 1.1.0 neměnil sadu Cockpit overrides. Neobsahuje samostatný OAuth provider.
Podrobnosti původní theme architektury: [docs/architecture.md](docs/architecture.md).

## Source

| Cesta | Obsah |
| --- | --- |
| src/ | Theme, login JS, české opravy a logo |
| sso/ | Staff relying party, lokální grants, Unix auth adapter, mapping CLI/UI, opt-in installer |
| scripts/ | Theme build/install/update/uninstall/rollback a source packaging |
| tests/ | Python, browser a společný Staff/SC HTTP kontrakt |
| docs/ | Architektura, SSO, kompatibilita a ověření |

Snapshot a etc-cockpit nejsou source ani release obsah. Archiv používá explicitní
allowlist a MANIFEST.sha256; neobsahuje runtime config, sessions nebo credentials.

## Lokální ověření

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install cryptography==48.0.1
python scripts/fetch_test_upstream.py
export DCI_UPSTREAM=build/upstream
python -m unittest discover -s tests -v
python scripts/preview.py --upstream build/upstream
npm ci --ignore-scripts
npm run test:browser
python tests/integration_staff.py ../staff-center-sso
python scripts/package.py
```

Fetcher existující build/upstream nepřepisuje. Browser test vyžaduje Chrome.
Společný kontrakt vyžaduje npm ci ve Staff checkoutu. PowerShell místo export:
`$env:DCI_UPSTREAM='build/upstream'`. Native PAM/systemd na tomto Windows neběží.

## Budoucí instalace/update theme

Po ověření checksumu release a MANIFEST.sha256, z nezávislé SSH relace:

```sh
sudo sh scripts/install.sh
# Aktualizace existující 1.1.0:
sudo sh scripts/update.sh
sudo python3 scripts/manage.py status
```

Z historické 1.0.0 nejprve její uninstall (jiná sada balíčků).
Přepnutí krátce ukončí Cockpit relace; ostatní služby nerestartuje. APT pre-hook
před balíčkovou transakcí theme deaktivuje. Po aktualizaci ji znovu vytvoří
update.sh jen pro podporovanou verzi. Před přímým dpkg nebo upgradem OS uninstall.

SSO se instaluje odděleně přes `sudo python3 -B sso/install.py install` až po
přípravě Staff registry, root-only configu, mapování a proxy. Podrobný postup
v docs/sso.md. Proxy ani konfigurace jiných aplikací se automaticky nemění.

## Rollback

```sh
sudo python3 -B sso/install.py uninstall  # pouze náš Staff SSO adapter
sudo sh scripts/rollback.sh               # předchozí kompatibilní theme generace
# Nebo původní Cockpit:
sudo sh scripts/uninstall.sh
```

Odstranit samostatně pouze SSO proxy location a Staff service registraci.
Theme uninstall sám nevypíná SSO. Adapter uninstall ponechá config a mapy;
heslová autentizace zůstává. Generace theme se uchovávají pro audit.
SSO assertion contract, Debian dependency and native test: [docs/sso-verification.md](docs/sso-verification.md).

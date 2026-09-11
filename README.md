# DiamondCrew Interactive

## Server Controller · 1.1.0

Samostatný reskin skutečného Cockpit **287.1-0+deb12u3**, Debian GNU/Linux 12.
Moduly a heslové přihlášení nadále obsluhuje Cockpit. Volitelný Discord adaptér
ověří externí identitu, mapuje ji na existující UID a otevře relaci přes account,
credential a session části PAM služby Cockpit. Neuděluje nová oprávnění.

Stav: implementováno a lokálně ověřeno na snapshotu a statických browser fixtures.
Skutečný backend a systémová instalace na Debianu dosud nejsou integračně ověřeny.
Repozitář projektu: https://github.com/DIamondCrew-Interactive/web-servercontroller.
Zamýšlený produkční endpoint: https://admin.diamondcrew.net. Nástroje se na něj nepřipojují.

## A. Architektura

`src/theme.css` obsahuje navy paletu, gradient `#2ec7ff → #f43cb2 → #f3d36b`,
PatternFly 4 proměnné a komponentové styly. `src/branding.css` doplňuje login.
`src/assets/logo.png` je přesná kopie dodaného loga. Nepoužívají se CDN, vzdálené
fonty ani telemetry. `src/login.js` přidává volitelný Discord tok a korekce českých
popisků; `src/locales/cs.json` upravuje české katalogy generovaných modulů.
Úvodní karta obsahuje logo, plný brand, Discord tlačítko, heslový formulář a slogan
**Create. Play. Together.** Včetně světlého uživatelského režimu zůstává tmavá.

Cockpit 287.1 nemá globální theme API pro všechny iframy. Generátor proto kopíruje
osm existujících frontendových balíčků z `/usr/share/cockpit` do nové generace a
do 14 HTML dokumentů přidává jeden relativní odkaz na `dci_theme/theme.css`.
Do `shell/index.html` přidává navíc statický brand blok před navigaci.
Upstream manifesty, CSS a aplikační JavaScript zachovává byte-for-byte. Výjimkou
jsou cílené řetězce v českých `po.cs.js.gz` katalozích (shell, metrics, users).
Nový samostatný modul `dci_discord` přidává správu přiřazení účtů do navigace.
Layout skutečného overview se nepřestavuje.

Generace se aktivuje odkazy z `/usr/local/share/cockpit/<package>`. Cockpit podle
XDG pravidel vybere lokální balíček před `/usr/share/cockpit`. Jde o překrytí
celého balíčku, nikoli o automatický fallback jednotlivých chybějících souborů.
Proto se kopírují celé balíčky, místo nefunkčních miniaturních balíčků jen s HTML.
Upstream adresáře zůstávají nedotčené. Soubory jsou generované z aktuálního cílového
stroje, nikoli z přiloženého produkčního snapshotu.

Login a shell již načítají `branding.css`. Na Debianu 287.1 je aktivní distribuční
soubor `/usr/share/cockpit/branding/debian/branding.css`; instalátor jej evidovaně
odkloní pomocí `dpkg-divert` a vytvoří odkaz na naši generaci. Druhý diversion
chrání `/usr/share/cockpit/static/login.html`; kopie zachovává původní autentizační
JS a DOM prvky, přesouvá detaily dovnitř karty a přidává Discord tlačítko.
Náš `dc-logo.png` a `dci-login.js` se servírují branding loaderem. Samotný theme
nemění PAM, cockpit.conf ani systémové jednotky. Samostatná instalace Discord
adaptéru přidává bearer sekci do cockpit.conf a vlastní systemd jednotky;
postup a hranice jsou v [docs/discord.md](docs/discord.md).

Přesné podklady a alternativy: [docs/architecture.md](docs/architecture.md).

## B. Source struktura

| Cesta | Účel |
| --- | --- |
| `src/` | Produkční CSS a dodané logo |
| `discord/` | Volitelný OAuth broker, root auth adaptér, správa mapování, UI a systemd templates |
| `compatibility.json`, `VERSION` | Přesná cílová verze a balíčky |
| `scripts/build.py` | Generování overlay z instalace/snapshotu |
| `scripts/manage.py` | Kontroly, generace, dpkg-divert, APT, rollback |
| `scripts/{install,update,uninstall,rollback}.sh` | Debian entrypointy |
| `scripts/package.py` | Lokální allowlist source archiv + kontrolní součty |
| `scripts/preview.py`, `preview/` | Statické náhledy, nikdy se neinstalují |
| `tests/` | Integrita, simulace lifecycle a browser assertions |
| `docs/` | Rozhodnutí, kompatibilita, testy a kontrola před nasazením |

## C. Co je override a co upstream

Upstream balíčky ve snapshotu jsou vstupní distribuční artefakty, ne naše zdrojové
soubory. Všech 343 veřejných frontendových souborů odpovídá SHA256 souborů ze šesti
veřejných Debian `.deb` přesné verze; URL a SHA256 balíčků jsou připnuté v
`tests/debian-packages.json`. Výchozí inventář zároveň potvrzuje nezměněný snapshot.
`docs/snapshot-sha256.json` obsahuje jen cesty veřejných assetů a hashe.

Naše override: CSS, brand blok, vložené `<link>`, české překlady, login HTML a
samostatné Discord soubory. Generované aplikační JS/manifests jsou upstream.
`base1`, `ssh`, `tuned` (manifest name `performance`) a další moduly se nenahrazují. Overview,
metrics, služby, logy, síť/firewall, storage, accounts, apps, updates, terminál a
hardware info dostávají společné CSS. Ostatní případně doinstalované moduly zůstávají
dostupné, ale jejich vzhled není tímto profilem garantován.

## D. Instalace na Debian 12

Provádí se později z root SSH relace v servisním okně: přepnutí prostředků dočasně
zastaví `cockpit.socket` a `cockpit.service`, ukončí Cockpit relace a znovu spustí
jednotky, které před operací běžely. Ostatní spravované služby se nerestartují.
Vyžaduje `python3`, `dpkg-query`, `dpkg-divert`, `systemctl` a všechny balíčky uvedené
v `compatibility.json` s přesnou verzí. Node/npm nejsou na serveru potřeba.

```sh
sha256sum -c SHA256SUMS
tar -xzf diamondcrew-servercontroller-1.1.0.tar.gz
cd diamondcrew-servercontroller-1.1.0
sha256sum -c MANIFEST.sha256
sudo sh scripts/install.sh
sudo python3 scripts/manage.py status
cockpit-bridge --packages
```

Přihlaste se znovu a proveďte hard refresh; Cockpit silně cachuje statické prostředky.
Instalátor odmítne cizí lokální balíčky, cizí diversion, změněný APT hook i jinou
verzi OS/Cockpitu. Nevymaže vlastní uživatelské overrides; ověřte pro každý účet
`cockpit-bridge --packages`, protože `~/.local/share/cockpit` má ještě vyšší prioritu.
Vlastní `XDG_DATA_DIRS` nebo jiný distro variant branding vyžaduje samostatnou validaci.

## E. Aktualizace

Při přechodu z 1.0.0 nejprve z SSH spusťte starý `uninstall.sh` (nebo zachovaný
`/var/lib/diamondcrew-servercontroller/current/source/scripts/manage.py uninstall`),
potom nový `install.sh`. Sada balíčků se rozšiřuje o `dci_discord`; instalátor
proto nepřeklopí 1.0.0 na 1.1.0 běžným update. Další aktualizace stejné sady
již používají následující postup.

Pro novou verzi theme rozbalte a ověřte nový source archiv a spusťte z něj:

```sh
sudo sh scripts/update.sh
```

Vytvoří se nová generace z aktuálně instalovaných balíčků. Jediný `current` symlink
se atomicky přepne při zastaveném Cockpitu. Předchozí generace zůstane dostupná.
Instalátor nic nestahuje a sám neaktualizuje Debian balíčky.

Před jakoukoliv APT transakcí obsahující dpkg hook vrátí původní Cockpit a odstraní
diversion. Je to záměrně konzervativní i pro nesouvisející aktualizace: nikdy nesmí
zůstat aktivní zastaralá kopie JavaScriptu. Theme se automaticky znovu nezapne.
Po dokončení použijte `update.sh`; nepodporovaná verze bude odmítnuta a Cockpit
zůstane ve svém původním vzhledu. Při chybě hooku APT transakce skončí chybou;
nejprve opravte/uninstallujte theme, potom opakujte aktualizaci.

Před přímým `dpkg -i`, ruční výměnou `/usr/share/cockpit`, upgradem OS nebo odstraněním
Cockpitu vždy spusťte `uninstall.sh`. Tyto operace obcházejí APT hook. Nové revize
Cockpitu vyžadují kontrolu selektorů a testy; pouze změnit číslo kompatibility nestačí.

## F. Rollback / uninstall

```sh
sudo sh scripts/rollback.sh   # předchozí theme, pouze při totožných upstream hashech
sudo sh scripts/uninstall.sh  # původní Cockpit; lze bezpečně opakovat
```

Uninstall odstraní jen vlastněné symlinky a náš nezměněný APT hook, zruší diversion
a vrátí původní Debian CSS i login HTML. Zachová generace a audit v
`/var/lib/diamondcrew-servercontroller`. Nepřepisuje cizí pozdější úpravy.
Při přerušené aktivaci spusťte uninstall z root SSH. Funguje i ze zachovaných nástrojů:

```sh
sudo python3 /var/lib/diamondcrew-servercontroller/current/source/scripts/manage.py uninstall
```

Rollback po změně upstream souborů je odmítnut, aby nevrátil starý kód. Místo něj
použijte uninstall, případně update z kompatibilního source. Staré generace se
automaticky nemažou; obsahují pouze veřejné frontendové prostředky a naše nástroje.

## G. Lokální ověření a distribuční archiv

Reprodukovatelné ověření z čistého checkoutu, bez produkčního snapshotu:

```sh
python scripts/fetch_test_upstream.py
export DCI_UPSTREAM=build/upstream
python scripts/build.py --upstream build/upstream --output build/review
python -m unittest discover -s tests -v
python scripts/preview.py --upstream build/upstream
npm ci --ignore-scripts
npx playwright install chrome
npm run test:browser
python scripts/package.py
```

Fetcher pouze rozbaluje veřejné UI soubory z `.deb`, nic neinstaluje. Pokud již
`build/upstream` existuje, použijte existující ověřený výstup nebo novou výstupní
cestu; fetcher existující adresář nepřepíše. V PowerShellu použijte
`$env:DCI_UPSTREAM = 'build/upstream'`. Původní lokální snapshot lze nadále zadat
jako `DCI_UPSTREAM=../cockpit`; není součástí repozitáře.

Browser test používá místní Chrome. `DCI_BROWSER=msedge` přepne na Edge.
Výstupy: `build/preview/index.html`, `build/preview/login.html`, `build/screenshots/`
a `dist/diamondcrew-servercontroller-1.1.0.tar.gz` + `SHA256SUMS`.
Statické náhledy používají původní CSS a login HTML, ale ručně sestavená ukázková
data a markup modulů. Nejsou screenshotem skutečného admin rozhraní po přihlášení.

Source archiv má explicitní allowlist, kontrolu známých formátů privátních klíčů
a tokenů a per-file `MANIFEST.sha256`. Neobsahuje snapshot, `etc-cockpit`, diagnostiku,
node_modules ani generované upstream kopie. Lokální `package.py` nic nepublikuje.
Workflow `.github/workflows/release.yml` spouští testy/build na `main` a PR;
při pushi tagu odpovídajícího `VERSION` publikuje po úspěchu testů GitHub Release
s archivem a `SHA256SUMS`. Žádný workflow nenasazuje na server.
Podrobný výsledek je v [docs/test-results.md](docs/test-results.md).

## H. Co není lokálně ověřeno

Discord Client ID/Secret nejsou součástí source. Bez nakonfigurovaného adaptéru
zůstává Discord tlačítko neaktivní a funguje původní heslový formulář. OAuth HTTP
tok je testovaný s mockem Discord API, ne proti skutečné Discord aplikaci.
Root PAM/Unix socket adaptér a Nginx konfigurace vyžadují test na disposable Debianu
před aktivací na reálném hostu. Theme uninstall nenahrazuje uninstall volitelného
Discord adaptéru; oba postupy jsou oddělené.

Na Windows bez WSL nelze spustit skutečný Debian Cockpit/PAM/systemd backend.
Mockované lifecycle testy nejsou důkazem funkčnosti reálného dpkg-divert, APT hooku,
systemctl ani POSIX atomického rename. Neověřeny zůstávají přihlášení/PAM challenge,
administrátorská eskalace, WebSocket/CSP, reverse proxy, multi-host, reálné React
dialogy, všechny stavy modulů a xterm interakce. Barvy a zobrazení grafů při všech
metrikách vyžadují živý test. Favicon a dynamické titulky host/modul zůstávají upstream.

Layout skutečných modulů se zachovává; ilustrace serveru a nová dashboardová data
z referenčního obrázku se nevymýšlejí. Source Staff Center/Server Manager nebyl dodán;
vizuální sjednocení vychází z uvedené palety a reference. Před produkční instalací
proveďte [docs/debian-validation.md](docs/debian-validation.md) na testovacím Debianu.

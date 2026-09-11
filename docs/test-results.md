# Výsledky lokálního ověření

Datum: 2026-09-11. Host: Windows, Python 3.13.14, Node 22.14.0,
Playwright 1.63.0, Chrome 153.0.8010.36. Linux/WSL není dostupný.

Původní lokální sada: **14 Python testů PASS, 20 browser assertions PASS**, žádný
přeskočený Python test. Release sada doplňuje dva testy bezpečné extrakce Debian
assetů a kontroly checksumů, tedy 16 Python testů. Aktuální archiv má explicitní
allowlist; jeho přesný obsah dokládá přiložený `MANIFEST.sha256`.

Před publikací bylo ověřeno všech 343 veřejných frontendových souborů také proti
šesti veřejným Debian balíčkům 287.1-0+deb12u3. Všechny cesty i SHA256 odpovídají.
`tests/debian-packages.json` připíná URL a SHA256 stažených `.deb`; CI je pouze
rozbaluje pro testy. Žádné host konfigurace ani produkční credentials nepotřebuje.

| Kontrola | Výsledek / rozsah |
| --- | --- |
| Integrita snapshotu | SHA256 všech 343 veřejných frontendových souborů odpovídá výchozímu inventáři |
| Generátor na skutečném snapshotu | 8 module overlay balíčků + dci_theme, přesně 14 HTML vstupů |
| Zachování upstreamu | Po odebrání theme linku a shell brand bloku HTML odpovídá vstupu; JS/CSS/manifests jsou byte-for-byte totožné |
| Relativní package odkazy | Všech 14 HTML odkazuje na existující theme CSS; testovaná i vnořená cesta |
| Odmítnutí chybných vstupů | Dvojí patch, chybějící/duplicitní head, změněná shell struktura; neúplný build se uklidí |
| Lifecycle simulace | Install → update → rollback → uninstall, opakovaný uninstall, APT fallback a regenerace nového upstream JS |
| Ochranné scénáře | Cizí override, ručně změněný override, nepodporovaná verze, zastaralý rollback, simulovaná chyba během první aktivace |
| Browser | 20 assertions: login, plný brand, chybové hlášení, mobilní šířka, iframe CSS, moduly, disabled pole, focus, modal, Escape, nulové HTTP/page errors |
| Screenshoty | Login desktop/mobile, overview desktop/mobile, modal desktop; vizuálně zkontrolováno |
| Source archiv | Allowlist, reprodukovatelnost, SHA256 každého souboru a shell executable módy ověřeny testem |
| Shell syntax | `bash -n` všech čtyř entrypointů |

Testy se spouštějí podle README. Výstup browser testu je v
`build/browser-results.json`, screenshoty v `build/screenshots`.
`build/` se nedistribuuje jako produkční balíček.

Python lifecycle testy používají skutečné dočasné soubory a symlinky, ale simulují
`dpkg-divert`, `systemctl` a kontrolu Debian verze. Na Windows je navíc simulovaný
POSIX replacement adresářového symlinku, který Windows neumí stejným voláním.
Proto jejich úspěch není důkazem skutečné Debian transakce ani atomického přepnutí.

Browser test používá upstream CSS a původní login markup bez autentizačního JS.
Modulové fixtures jsou ručně sestavené statické ukázky. Neověřují skutečný React
render, PAM, eskalaci privilegií, systemd, D-Bus, networking/storage operace,
PackageKit, xterm, multi-host, CSP ani produkční reverse proxy.

Žádný backend nebyl lokálně spuštěn. Nebyly použity produkční credentials ani
proveden deployment na DIA-01. Výsledky release CI jsou dostupné v GitHub Actions;
publikační job se spustí pouze po úspěšném test/build jobu pro tag.

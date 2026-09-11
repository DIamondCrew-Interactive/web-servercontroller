# Architektonické rozhodnutí — Cockpit 287.1

## Zjištění ze snapshotu

343 veřejných frontendových souborů, 5 471 665 bajtů. Verzi potvrzuje seznam
Debian balíčků `287.1-0+deb12u3`; soubor `cockpit-version.txt` neobsahuje použitelný
výstup. Soubory `.js.gz` a `.css.gz` jsou produkční build artefakty, nikoli zdrojový
React projekt. JSON manifesty definují nabídku, parent vazby, překlady i bridge
konfiguraci. `shell/index.html` vytváří prostor pro moduly v iframech.

| Oblast | Skutečný vstup |
| --- | --- |
| Přihlášení | `static/login.html`, `login.js`, `login.css`, distro branding |
| Navigace / hlavička | `shell/index.html`, `index.js.gz`, `index.css.gz` |
| Overview / hardware / služby / logy / terminál | `systemd/*.html` |
| Metriky | `metrics/index.html` |
| Networking / firewall | `networkmanager/index.html`, `firewall.html` |
| Storage | `storaged/index.html` |
| Updates | `packagekit/index.html` |
| Accounts / apps | `users/index.html`, `apps/index.html` |
| API | `base1/cockpit.js.gz` |
| Performance profil | `tuned/`, jehož manifest nastavuje name `performance` |

`etc-cockpit/` je host configuration: obsahuje `cockpit.conf`, `disallowed-users`
a certifikát s privátním klíčem. Tyto soubory se nečtou do generátoru, nekopírují
a nedistribuují. Host status/socket výpisy nejsou potřebné pro frontendový balíček.
Referenční design je vizuální podklad, nikoli provozní konfigurace.

## Ověřené možnosti upstreamu

[Branding dokumentace přímo pro tag 287.1](https://github.com/cockpit-project/cockpit/blob/287.1/doc/branding.md)
popisuje pořadí distro/variant/default branding adresářů a CSS pro login/navigaci.
[Implementace branding roots v 287.1](https://github.com/cockpit-project/cockpit/blob/287.1/src/ws/cockpitbranding.c)
potvrzuje i explicitní XDG static roots. Globální změna prostředí web service by
ovlivňovala širší lookup a vyžadovala zásah do konfigurace služby; není zde zvolena.

[Dokumentace packages pro 287.1](https://github.com/cockpit-project/cockpit/blob/287.1/doc/guide/packages.xml)
popisuje XDG prioritu lokálních balíčků, manifest overrides a relativní package URL.
Manifest override je vhodný pro menu metadata, ne pro vložení CSS do existujících
HTML dokumentů. Balíček se nahrazuje jako celek. JSON menu ani privileged bridge
se proto neupravují a manifesty se zachovávají přesně.

[Release notes 347](https://cockpit-project.org/blog/cockpit-347.html) uvádějí až
v této verzi site-specific `/etc/cockpit/branding/`. Použít tento adresář jako
hotové řešení pro 287.1 by bylo nesprávné.

## Zvolené řešení

1. Jedno společné CSS a původní dodané logo v čistém source balíčku.
2. Generované kopie osmi existujících frontendových balíčků; 14 změn HTML a jeden
   statický brand blok. Žádný patch minifikovaného JavaScriptu, CSS či API.
3. Lokální XDG package odkazy míří přes jediný `current` pointer na generaci.
4. Login používá původní CSS loader s evidovaným odklonem jednoho Debian souboru.
5. APT přepne zpět na upstream před spuštěním dpkg. Reaktivace je výslovná,
   ověřuje přesnou verzi a generuje čerstvé kopie.

Nejde o výrobcem garantované globální theme API. Package precedence a branding
loader jsou existující mechanismy; vlastní HTML/CSS adaptér je úzce vázaný na
287.1. Update-safe zde znamená nepřepisovat distribuční moduly, zachovat původní
branding přes diversion a při upgradu automaticky deaktivovat kopie. Neznamená
to garantovaný vzhled na libovolné budoucí verzi.

Mechanismus diversion vychází z [Debian dpkg-divert(1)](https://manpages.debian.org/bookworm/dpkg/dpkg-divert.1.en.html).
APT lifecycle hook vychází z [Debian apt.conf(5)](https://manpages.debian.org/bookworm/apt/apt.conf.5.en.html).
Vlastní soubory se při konfliktu nepřepisují. Operace jsou serializované flockem;
aktivace probíhá při zastaveném Cockpitu. Při výpadku napájení v průběhu přepnutí
je dostupný explicitní recovery uninstall, nikoli slib úplné crash transakčnosti.

## Vzhled a hranice

Barevné proměnné a selektory se opírají o skutečné PF4 classy v decomprimovaných
bundlech snapshotu. Karty, formuláře, tabulky, dropdowny, modaly, toolbar a shell
mají navy povrchy, jemné hranice a modrý focus. Primární akce používají gradient.
Success/warning/danger význam se zachovává; destruktivní a disabled tlačítka se
nepřebarvují na běžnou primární akci. Obsah terminálu a ANSI paleta se neupravují.
Nejsou přidané plošné visibility overrides ani skrývání privilegií či chyb.

Přiložený obrázek ukazuje zamýšlený směr; nové funkční dashboard cards by vyžadovaly
nový frontend a další API integraci. Tento balíček přestyluje původní Cockpit layout.
Náhledové fixture CSS/JS se do deploymentu nekopíruje a není důkazem finálního
rozložení živého React UI. Pro remote hosty ověřte package výběr a branding zvlášť.

## Serverové cesty

```text
/var/lib/diamondcrew-servercontroller/
  state.json, lock
  current -> generations/<timestamp-id>
  generations/<timestamp-id>/
    packages/{shell,systemd,metrics,networkmanager,storaged,packagekit,users,apps,dci_theme}/
    branding/{branding.css,dc-logo.png}
    source/{scripts,src,VERSION,compatibility.json}
    build.json
/usr/local/share/cockpit/<package> -> /var/lib/.../current/packages/<package>
/usr/share/cockpit/branding/debian/branding.css -> /var/lib/.../current/branding/branding.css
/usr/share/cockpit/branding/debian/branding.css.dci-original
/usr/share/cockpit/branding/debian/dc-logo.png -> /var/lib/.../current/branding/dc-logo.png
/etc/apt/apt.conf.d/90diamondcrew-servercontroller
```

Generace obsahují pouze veřejné frontendové soubory a naše nástroje. TLS/PAM/host
konfigurace se nikdy neukládají. Nová generace potřebuje přibližně velikost osmi
frontendových balíčků navíc; staré generace se ponechávají pro audit.

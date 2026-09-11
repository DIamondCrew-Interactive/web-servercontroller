# DiamondCrew Interactive / Server Controller 1.0.0

Reskin skutečného Cockpitu pro Debian 12 a přesnou verzi **287.1-0+deb12u3**.
Navy vzhled, dodané logo, blue/pink/gold akcenty, login, navigace a společné
styly modulů. Původní JavaScript, manifesty, autentizace a API zůstávají zachované.

Distribuční asset je `diamondcrew-servercontroller-1.0.0.tar.gz` spolu se souborem
`SHA256SUMS`. Archiv obsahuje instalační source a vlastní `MANIFEST.sha256`;
neobsahuje produkční snapshot, host configuration, klíče ani generované upstream kopie.

## Instalace

Z nezávislé SSH relace na kompatibilním Debianu 12, v servisním okně:

```sh
sha256sum -c SHA256SUMS
tar -xzf diamondcrew-servercontroller-1.0.0.tar.gz
cd diamondcrew-servercontroller-1.0.0
sha256sum -c MANIFEST.sha256
sudo sh scripts/install.sh
sudo python3 scripts/manage.py status
cockpit-bridge --packages
```

Přepnutí dočasně zastaví Cockpit a ukončí jeho relace. Znovu se přihlaste a
proveďte hard refresh. Další podmínky a recovery postupy jsou v README.

## Update a rollback

```sh
sudo sh scripts/update.sh
sudo sh scripts/uninstall.sh  # návrat na původní Cockpit
```

Pokud existuje předchozí theme generace se stejnými upstream hashi:

```sh
sudo sh scripts/rollback.sh
```

APT hook před balíčkovou transakcí deaktivuje theme, aby nepřekrývala nový upstream
starými kopiemi. Reaktivace přes update je výslovná a kontroluje přesnou verzi.
Před přímým `dpkg -i` nebo upgradem OS spusťte uninstall.

## Ověření

CI před publikací spouští Python testy, build overlay nad šesti veřejnými Debian
balíčky s pevnými SHA256, browser testy a build/checksum source archivu.
Všechny veřejné frontendové soubory testovacího vstupu se porovnávají s původním
SHA256 inventářem. Žádná data z DIA-01 se v CI nepoužívají.

Lifecycle testy simulují systémové příkazy; browser testy používají statické
fixtures. Skutečný Debian backend/PAM/systemd a živé moduly vyžadují integrační
ověření podle `docs/debian-validation.md`. Release nic nenasazuje na DIA-01.

# DiamondCrew Interactive / Server Controller 1.1.0

Centrální tmavá přihlašovací karta, logo, opravené české popisky a slogan Create. Play. Together. Bílé pozadí detailů serveru a přepínače hesla odstraněno.

Nový modul Discord účty umožňuje administrátorům přiřadit Discord ID existujícímu účtu serveru. Volitelný OAuth broker a Cockpit bearer adaptér přidávají Discord přihlášení. Vyžadují vlastní Discord aplikaci, chráněnou konfiguraci na serveru, reverse proxy a Debian integrační ověření. Samotná instalace theme Discord autentizaci nezapíná.

Kompatibilita: Debian 12, Cockpit 287.1-0+deb12u3. Přechod z 1.0.0 vyžaduje nejprve uninstall původní theme a následně install nové; viz README. Nová verze spravuje také dpkg diversion původního login.html.

Release balík: diamondcrew-servercontroller-1.1.0.tar.gz a SHA256SUMS. Archiv obsahuje source, testy a veřejné příklady konfigurace; bez credentials, snapshotu a generovaných upstream souborů.

Instalace, aktualizace a rollback: README. Samostatný Discord adaptér se instaluje a odstraňuje podle docs/discord.md; odinstalace theme jej nevypíná. Přepnutí theme přeruší Cockpit relace, používejte nezávislou SSH relaci.

Výsledky a omezení ověření: docs/test-results.md. Release workflow nic automaticky nenasazuje.

# Validační postup pro testovací Debian

Tento postup nebyl spuštěn na DIA-01. Nejprve použijte disposable Debian 12 se
stejnou Cockpit verzí. Mějte nezávislou SSH relaci: aktivace přeruší Cockpit relace.

1. Ověřte instalované balíčky, standardní XDG cesty a `cockpit-bridge --packages`
   pro skutečný administrátorský i neprivilegovaný účet. Zkontrolujte lokální a
   uživatelské overrides a případný OS variant branding.
2. Před instalací ověřte původní login, nesprávné heslo, PAM konverzaci (je-li
   nakonfigurována), odhlášení, opětovné přihlášení a omezený/admin přístup.
3. Instalujte source balíček. Ověřte `dpkg-divert --list` a symlinky. Porovnejte
   SHA256 upstream modulů před/po; změněná distribuční cesta má být jen branding.css
   přes evidovaný diversion. Znovu načtěte web bez cache.
4. Ověřte browser Network: CSS i logo vracejí 200, nevznikají CSP chyby a nejsou
   blokované WebSockety. Ověřte všechny iframe cesty včetně hwinfo/firewall.
5. Načtěte overview, metrics, services, logs, networking, storage, accounts,
   apps, updates, performance profil a terminal. Na testovacím stroji ověřte
   neškodnou změnu testovací služby, návrat stavu a reálné chybové dialogy.
6. Ověřte modal focus trap, Escape, dropdown, formulář valid/invalid/disabled,
   keyboard focus, délky českých textů, 200% zoom, mobilní shell navigaci a grafy.
   Warning/error/success a omezená oprávnění musí být čitelná.
7. V terminálu ověřte velikost, focus, kopírování, výběr a běžné ANSI barvy.
   Neověřujte destruktivní operace na produkčních discích či síti.
8. Ověřte update na druhou theme generaci a rollback. Při změně upstream hashe
   musí rollback odmítnout starou generaci.
9. Spusťte testovací APT transakci. Před dpkg musí zmizet lokální overrides a
   být obnoven původní branding. Po kompatibilním upgradu spusťte update. Po
   nekompatibilním upgradu musí zůstat upstream vzhled bez zastaralého JS.
10. Ověřte uninstall dvakrát, nové přihlášení, obnovení původních resources a
    zachování cizích files/overrides. Vyzkoušejte recovery po přerušené aktivaci.

Teprve úspěšný integrační test doloží provozní kompatibilitu. Windows unit testy
s mocky nemohou tuto validaci nahradit.

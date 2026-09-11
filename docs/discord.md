# Discord účty a přihlášení — volitelný adaptér 1.1.0

Stav: implementovaný source a lokální mock testy. Skutečné Discord OAuth a
Debian PAM/session/Unix socket propojení nebylo v tomto Windows prostředí spuštěno.
Neaktivovat na produkci bez ověření na disposable Debianu se stejným Cockpitem.

## Co se propojuje

Administrátor v modulu **Discord účty** vybere existující Linux účet a jeho
číselné Discord ID. UI používá Cockpit `spawn` se `superuser: require`; mapování
zapisuje výhradně root CLI. Není dostupné veřejné HTTP API pro přiřazování účtů.
Jeden Discord účet smí být přiřazen právě jednomu účtu serveru a naopak.
Pro změnu se musí staré přiřazení výslovně zrušit.

Mapování obsahuje username i UID. Pokud se účet smaže a znovu vznikne s jiným UID,
staré propojení přestane fungovat. Systémové účty, root, nologin účty, zamčené nebo
prázdné shadow heslo a účty v `/etc/cockpit/disallowed-users` se odmítají. Discord
role a členství na guild serveru nepřidávají oprávnění. Odebrání mapování blokuje
nová přihlášení; již otevřenou relaci samo neukončí.

## Přihlašovací tok

1. `/discord/start` vytvoří serverový OAuth state a naváže jej na HttpOnly cookie.
2. Discord authorization-code flow požaduje pouze scope `identify`.
3. `/discord/callback` ověří state, browser binding a expiraci. Kód se vymění
   za access token server-side a přes `/users/@me` se zjistí Discord ID.
4. Access/refresh token se neukládá ani neposílá do browser storage. Callback
   nastaví krátkodobý HttpOnly redeem handle a přesměruje na `/`.
5. Same-origin POST s kontrolou Origin a vlastním hlavičkovým markerem vydá
   jednorázový bearer ticket platný 30 sekund. Ten login JS předá Cockpitu.
6. Cockpit `[bearer] UnixPath` připojí root socket adaptér. Adaptér ověří Unix
   peer UID OAuth služby, atomicky spotřebuje ticket, znovu zkontroluje root-owned
   mapování, provede PAM account/credential/session kontroly, přepne UID/GID a
   spustí původní `cockpit-bridge`. Při skončení uzavře PAM session.

Použité upstream rozhraní: [Cockpit 287.1 authentication protocol](https://github.com/cockpit-project/cockpit/blob/287.1/doc/authentication.md).
Discord flow: [oficiální OAuth2 dokumentace](https://docs.discord.com/developers/topics/oauth2).
Původní password/PAM autentizace se nevypíná. Nastavení `[OAuth]` Cockpitu se
nepoužívá: jeho implicitní flow není tento serverový authorization-code flow.

Socket adaptér nahrazuje jen ověření prvního autentizačního faktoru pro bearer
login; nevolá password `pam_authenticate`. Account, setcred a session pocházejí
z PAM služby `cockpit`. Interaktivní PAM challenge při těchto fázích je odmítnuta,
nikoli automaticky schválena. PAM_RHOST je `discord-oauth`, nikoli IP browseru;
lokální PAM policy podle adresy vyžaduje samostatnou validaci. Původní Cockpit
sudo/polkit eskalace zůstává závislá na oprávnění účtu a případném heslu.

## Konfigurace aplikace a instalace

V Discord Developer Portal nastavte redirect URI přesně:

```text
https://admin.diamondcrew.net/discord/callback
```

Client ID je veřejné. Client Secret vložte pouze do chráněného souboru serveru;
nikdy do Gitu, chatu nebo argumentů shell příkazů. Z rozbaleného 1.1.0 source,
na testovacím Debianu, s nezávislou SSH relací:

```sh
sudo install -d -m 0755 /etc/dci-discord
sudo install -m 0600 discord/oauth.example.json /etc/dci-discord/oauth.json
sudoedit /etc/dci-discord/oauth.json
sudo python3 discord/install.py install --config /etc/dci-discord/oauth.json
```

Příklad konfigurace obsahuje prázdné `client_id` a `client_secret`; vyplňte je.
`origin` musí být HTTPS bez cesty, bez koncového lomítka. Příkaz `install` vyžaduje
Cockpit ws 287.1-0+deb12u3 a systémové skupiny `cockpit-ws`, `www-data`.
Nástroj vytvoří služební účet `dci-discord` a nastaví secret config na root:dci-discord
0640. Existující bearer sekci nepřepíše. Případná neúplná instalace má recovery
přes tentýž skript s `uninstall`.

Do stávajícího HTTPS Nginx server bloku přidejte pouze location z
`discord/nginx.conf.example`. Nesměrujte `/internal/` na OAuth broker.
Služba naslouchá výhradně Unix socketu, nikoli veřejnému TCP portu.
Potom ověřte konfiguraci a reload:

```sh
sudo nginx -t
sudo systemctl reload nginx
curl --fail https://admin.diamondcrew.net/discord/status
sudo systemctl status dci-discord.service dci-discord-auth.socket
```

Reverse proxy není automaticky přepisována. Příklad je pro Nginx a standardní
skupinu www-data; u jiné proxy je potřeba odpovídající socket access a routing.
OAuth callback access log je vypnutý, protože query obsahuje autorizační kód.
Theme 1.1 instaluje nové login HTML a UI; samotný theme adaptér nespouští.

## Přiřazení účtu

V Cockpitu otevřete **Discord účty → Načíst účty s administrátorským přístupem**,
vyberte účet a zadejte číselné Discord ID. Nebo z root SSH:

```sh
sudo python3 -B /usr/local/lib/dci-discord/accounts.py list
sudo python3 -B /usr/local/lib/dci-discord/accounts.py link --user EXISTUJICI_UCET --discord-id DISCORD_ID
sudo python3 -B /usr/local/lib/dci-discord/accounts.py unlink --user EXISTUJICI_UCET
```

Poslední dva příkazy obsahují zástupné hodnoty; nahraďte je vlastními údaji.
Neprovádí se reset hesla, useradd cílového účtu ani změny skupin/sudoers.

## Ověření a rollback

Ověřte správné, nepřiřazené a chybné Discord ID, root/zamčený/expirující účet,
opakovaný callback, opakovaný ticket a odhlášení. Zkontrolujte stejný UID i práva
v terminálu přes oba přihlašovací způsoby. Ověřte dostupnost heslového přihlášení
při vypnutém OAuth brokeru. PAM/Unix socket integrace je povinná součást staging testu.

```sh
sudo python3 discord/install.py uninstall
```

Uninstall ukončí OAuth relace a služby, odstraní vlastněné nezměněné jednotky/kód
a pouze označenou bearer sekci cockpit.conf. Heslový login se zachová. Secret
config, mapování a service účet se záměrně automaticky nemažou. Odstraňte také
vlastní `/discord/` location z reverse proxy a ověřte její reload.
Theme rollback je samostatné `scripts/uninstall.sh`.

## Provozní soubory mimo source

- `/etc/dci-discord/oauth.json`: Client Secret; root:dci-discord 0640.
- `/etc/dci-discord/accounts.json`: soukromé mapování ID; root 0600.
- `/var/lib/dci-discord/oauth.sqlite3`: krátkodobé hashe state/handle/ticket.
- `/run/dci-discord/http.sock`: broker přístupný proxy přes Unix socket.
- `/run/dci-discord-auth.sock`: Cockpit auth socket pro skupinu cockpit-ws.
- `/usr/local/lib/dci-discord/`: veřejný kód adaptéru, root-owned.
- `/var/lib/diamondcrew-discord-install.json`: metadata uninstall, bez secrets.

Tyto provozní soubory se nikdy nekopírují do source ani release archivu.

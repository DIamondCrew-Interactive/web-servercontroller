# Staff SSO → Server Controller 1.2.1

Staff broker je součástí samostatného repozitáře `web-staff`; jeho konfiguraci
popisuje tamní `docs/SSO.md`. Server Controller používá tento centrální broker,
nikoli samostatný Discord OAuth provider v Cockpitu.

## A. Architektura

Tlačítko **Pokračovat přes DiamondCrew Interactive** zahájí `/auth/sso/start`.
Server vytvoří browser-bound state a serverový verifier a pošle browser na
`https://staff.diamondcrew.net/sso/servercontroller?state=...&code_challenge=...`.
Staff využije stávající session, nebo provede svůj existující Discord OAuth.
Staff callback zůstává `/auth/discord/callback`. Server Controller nekomunikuje
s Discord API a nemá jeho Client ID/Secret.

Staff per-service allowlist povoluje vstup do konkrétní služby. Staff role/docs
policy je nezávislá. Staff neposílá Unix username: jedinou autoritativní identitou
je číselné Discord ID. Cílový Unix účet rozhoduje pouze lokální root-owned mapa.

## B. Ticket a session lifecycle

Staff uloží grant pod hashem 32bajtového náhodného tiketu. Browser dostane pouze
neprůhledný ticket, nikoli JSON/JWT s hesly nebo tokeny. Serverový grant obsahuje
`audience`, `subject`, `issued_at`, `expires_at`, `jti`, `state`, challenge a vazbu
na Staff session. TTL je 45 sekund. Staff redirect je pevný:
`https://admin.diamondcrew.net/auth/sso/callback?ticket=...&state=...`.

Callback ověří lokální state a HttpOnly cookie a přes ověřené HTTPS provede
`POST https://staff.diamondcrew.net/sso/api/redeem`. Použije samostatný servisní
Bearer secret a serverový verifier. Redirect při redeem je zakázán. Staff atomicky
ověří a spotřebuje ticket pro správnou audience a vrátí podepsaný Ed25519 JWT.
Server Controller ověří podpis, issuer, audience=servercontroller, state,
subject, jti a lifetime nejvýše 45 sekund. Návrat na pevné `/` odstraní ticket
z aktuální adresy; callback nesmí být logován proxy.

Lokální HttpOnly redeem handle platí 30 sekund. Same-origin POST s kontrolou Origin
a vlastní hlavičkou jej jednorázově vymění za další lokální bearer platný 30 sekund.
Ten login JS odešle původnímu Cockpit login endpointu. Nejde o prodloužení platnosti
Staff tiketu: ten již byl spotřebován a nelze jej znovu použít.

`cockpit-ws` použije podporované `[bearer] UnixPath`. Privilegovaný adaptér ověří
peer UID lokálního SSO brokeru, spotřebuje lokální bearer, ověří mapování a účet,
provede PAM account/credential/session fáze a spustí původní `cockpit-bridge`
pod cílovým UID/GID a skupinami. Cookie skutečné Cockpit session vydává Cockpit.
Nedoplňujeme ji frontendovým JavaScriptem a nepoužíváme Linux heslo jako credential.

To je alternativní passwordless autentizace, ne gateway před heslem. `[basic]`
zůstává zachován. Zvýšení oprávnění přes sudo/polkit může nadále vyžadovat heslo.
PAM auth pravidla nejsou automaticky přenesena: adaptér explicitně kontroluje
disallowed-users, zamčené/prázdné shadow heslo, login shell a odmítá root/system
účty. `PAM_RHOST=staff-sso`, nikoli původní klientská IP. PAM lifecycle a skutečná
ws cookie session prošly izolovaným testem na DIA; viz docs/test-results.md.
Reálný browser/password/sudo E2E je nadále samostatná neověřená hranice.

Staff logout zneplatní jeho session a dosud nevyměněné tikety. Cockpit logout
ukončí Cockpit session; uživatel může být stále přihlášen na Staff. Endpoint
`POST /auth/sso/logout` zruší jen nevyzvednutý lokální handle, není náhradou
Cockpit logoutu. Federované odhlašování není implementované. Odebrání mapování
blokuje nové relace; existující relace samo nezabije.

## C–D. Source a lifecycle

- Staff: obecný registry klientů, issuance route, autentizovaný redeem, pokračování
  po existujícím OAuth loginu; žádná druhá implementace Discord loginu.
- Server Controller: `sso/broker.py`, `grants.py`, `auth.py`, `accounts.py`, CLI,
  systemd jednotky a opt-in `sso/install.py`. Starý adresář `discord/` s přímým
  OAuth kódem je odstraněn.
- `scripts/install.sh`/`update.sh`/`uninstall.sh`/`rollback.sh` dál spravují pouze
  theme. Aktualizovaný generátor kopíruje nový SSO source. Instalace theme
  neaktivuje bearer auth ani nepřepisuje proxy.
- Název Cockpit balíčku `dci_discord` je zachován kvůli kompatibilitě přechodu
  z 1.1.0; slouží už jen ke správě lokálních Discord ID mapování.

## E. Lokální mapping

`/etc/diamondcrew-servercontroller/discord-users.json`, root:root 0600:

```json
{
  "584274123622973440": {"username": "skopy", "uid": 1001}
}
```

UID je příklad, CLI zjistí skutečný UID z NSS. Pin UID brání přenosu identity po
smazání a opětovném vytvoření username. Jeden Discord ID a jeden účet mají nejvýše
jedno propojení. Root, systémové účty a nologin účty nelze propojit.

```sh
sudo dci-servercontroller sso link skopy 584274123622973440
sudo dci-servercontroller sso list
sudo dci-servercontroller sso show skopy
sudo dci-servercontroller sso unlink 584274123622973440
```

Změna mapování nepotřebuje rebuild ani restart. CLI má root kontrolu, flock,
atomický zápis a odmítá přepsání existujícího propojení. Žádné heslo se neukládá.
Administrativní Cockpit modul používá spawn se superuser=require. Mapování nikdy
nevydává veřejný SSO HTTP endpoint; root správce je může zobrazit CLI nebo modulem.

## F. Konfigurace a hranice

SC config: `/etc/diamondcrew-servercontroller/sso.json`, root:root 0600.
Klíče: `origin`, `staff_origin`, `audience`, `redeem_secret`, `verification_keys`;
viz `sso/sso.example.json` a [podepsaný kontrakt a nativní test](sso-verification.md).
Unknown keys a Discord OAuth credentials se odmítají. Secret je náhodná nejméně
32bajtová base64url servisní credential pouze této audience, shodná se Staff
registry. Není to Discord secret. Origin config čte neprivilegovaný broker přes
systemd LoadCredential; soubor zůstává root-only.

SSO broker je důvěryhodná autentizační komponenta. Kompromitace brokeru nebo Staff
může ohrozit mapované účty. Lokální root mapa omezuje cílové účty, nemůže však
ověřit identitu nezávisle na kompromitovaném centrálním providerovi. Chrání se
Unix sockety, parent adresáře, credentials a kód. Nevkládat service secret do UI.

Staff používá jeden proces a in-memory sessions/tickets. Restart tikety revokuje.
Více replik potřebuje sdílenou atomickou session/grant databázi; není nyní podporováno.
Lokální SC grants jsou SQLite a jejich consume je transakční. Obě strany odmítají
replay, cizí audience, špatný verifier/state a expirované credentials.

## G. Proxy Manager později

Staff registry přidá `proxymanager`, vlastní credential, allowedIds a pevný
`https://proxy.diamondcrew.net/auth/sso/callback`. Proxy Manager použije stejné
claims, ale vlastní mapu Discord ID -> NPM user a svůj session adapter. SC ticket
nesmí přijmout a jeho credential nesmí sdílet. NPM integrace se nyní neimplementuje.

## H. Testy

SC (ve venv s `pip install cryptography==48.0.1`):
`DCI_UPSTREAM=build/upstream python -m unittest discover -s tests -v`;
`python scripts/preview.py --upstream build/upstream`; `node tests/browser.cjs`.
Staff: `npm test`; `npm run build`.
Společný kontrakt: `python tests/integration_staff.py /path/to/web-staff` po
`npm ci` ve Staff checkoutu. Používá skutečné HTTP routy obou aplikací, mockuje
jen Discord API a přesměrování HTTPS transportu do lokálního HTTP fixture.
Neprovádí Linux PAM, skutečný Discord login, produkční proxy ani deployment.

## I. Deployment pořadí

1. Uchovat deployment zálohu a nezávislou SSH relaci. Nativní PAM, Unix identity
   a ws cookie gate jsou potvrzené pro Cockpit 287.1-0+deb12u3. Naplánovat kontrolu
   reálného Discord browser loginu, heslového fallbacku a sudo/polkit E2E;
   tyto scénáře dosud nejsou potvrzené a sudo konfigurace se nemění.
2. Použít release 1.2.1; existující tag 1.1.0 se nepřepisuje.
3. Nasadit Staff s SSO nejprve vypnutým, připravit privátní registry a runtime
   credential podle Staff docs/SSO.md, potom zapnout pouze servercontroller.
4. Na SC ověřit release checksum a manifest, z 1.1.0 spustit `scripts/update.sh`.
   Pro historickou 1.0.0 nejprve její uninstall, protože měla jinou sadu balíčků.
5. Připravit root-only config se servisním secret a veřejnými Staff klíči.
   Z rozbaleného, ověřeného release spustit theme update a první opt-in SSO:

```sh
sha256sum -c MANIFEST.sha256
sudo apt-get install python3-cryptography
sudo sh scripts/update.sh
sudo python3 scripts/manage.py status
# Existující config vygenerovaný rootem nepřepisovat example souborem:
sudo chown root:root /etc/diamondcrew-servercontroller/sso.json
sudo chmod 0600 /etc/diamondcrew-servercontroller/sso.json
sudo python3 -B sso/install.py install --config /etc/diamondcrew-servercontroller/sso.json
sudo dci-servercontroller sso link skopy 584274123622973440
sudo dci-servercontroller sso show skopy
sudo systemctl is-active cockpit.socket dci-sso.service dci-sso-auth.socket
curl -kI https://127.0.0.1:9090
```

Instalátor neakceptuje neodinstalovaný starý samostatný Discord backend nebo cizí
bearer sekci. Starý backend, pokud byl ručně zapnutý, odstranit jeho původním
instalátorem před instalací Staff SSO. Mapy se automaticky nepřevádějí.

6. Zpřístupnit pouze `/auth/sso/` z `sso/nginx.conf.example`; nikdy `/internal/`.
   U NPM v Dockeru je nutné navrhnout přístup k host Unix socketu (mount + UID/GID),
   snippet sám host socket do kontejneru nepřipojí. Proxy se zde nemění. Nelogovat
   callback query, request body, Location ani Authorization. Ověřit dostupnost
   status endpointu a skutečné přihlášení oběma metodami.

Další adapter update: `sudo python3 -B sso/install.py update`. Ten zastaví vlastní
SSO relace, odstraní vlastní soubory a znovu instaluje; config a mapy zachová.
Při neúspěchu zůstává heslová metoda, použít uninstall k odstranění partial stavu.

Rollback adaptéru: `sudo python3 -B sso/install.py uninstall`, odstranit pouze
jeho proxy location a zakázat jeho Staff registry položku. Samostatný theme
rollback: `sudo sh scripts/rollback.sh`, případně uninstall pro původní Cockpit.
Návrat k jinému adaptéru vyžaduje jeho odpovídající config a vlastní instalátor;
neaktivovat zpět historický Discord OAuth automaticky. Secrets a mapy se nemažou.

Z ponechaného rozbaleného release při návratu na předchozí theme 1.1.0:

```sh
sudo python3 -B sso/install.py uninstall
sudo sh scripts/rollback.sh
sudo python3 scripts/manage.py status
sudo systemctl is-active cockpit.socket
```

Nejprve odstranit adaptér, potom vrátit theme. SSO proxy route a Staff registraci
vrátit z odpovídající deployment zálohy samostatně; theme rollback je nespravuje.

## Installer 1.2.1 and restrictive umask

The installer supports root umask 077 without changing the caller's umask.
It explicitly sets its own runtime directory to 0755, code/units to 0644, CLI to
0755, and secret/state files to 0600. Original cockpit.conf mode and ownership
are saved for uninstall. Only an empty root-owned managed target is repaired;
existing unrelated non-traversable parents cause a preflight error.
Run the isolated installer regression command in docs/test-results.md first.
After the failed 1.2.0 installation was rolled back, use `install`, not `update`,
for the first SSO activation; existing config/mapping are preserved.

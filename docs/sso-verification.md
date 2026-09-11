# Podepsaný Staff kontrakt a nativní ověření

Pracovní zdroj 1.2.0, bez publikace a deploymentu. Přímý Discord OAuth je pouze
ve Staff. Server Controller je relying party a lokální správce mapování.

## Redeem a assertion

Browser dostane opaque jednorázový ticket (32 náhodných bajtů, base64url43),
callback je `/auth/sso/callback?ticket=...&state=...`. Lokální state je svázaný
s HttpOnly cookie. Verifier je uložený jen na serveru, challenge je SHA256.

SC odešle přes ověřené HTTPS na Staff `/sso/api/redeem` JSON
`{ticket,audience:"servercontroller",state,code_verifier}` a per-service
`Authorization: Bearer <redeem_secret>`. Redirecty redeem jsou zakázané.
Odpověď musí být přesně `{assertion:<JWT>,token_type:"DCI-SSO",expires_in:45}`.

JWT header je přesně `{alg:"EdDSA",typ:"JWT",kid:"dci-20260911"}`.
Claims jsou přesně `iss`, `aud`, `sub`, `iat`, `exp`, `jti`, `state`:

- `iss`: `https://staff.diamondcrew.net`, bez koncového lomítka.
- `aud`: string `servercontroller`; jiné služby i array jsou odmítnuté.
- `sub`: canonical Discord ID jako desetinný string, nikdy Unix username.
- `iat` a `exp`: integer epoch sekundy, lifetime nejvýše 45 sekund.
  Iat smí být nejvýše 5 sekund v budoucnosti, exp musí být stále platné.
- `jti`: canonical lowercase UUIDv4, kompatibilní s Node `randomUUID()`.
- `state`: původní base64url43 browser state.

SC ověřuje pouze lokálně zadané Ed25519 PEM veřejné klíče v konfiguraci
`verification_keys: {"dci-20260911":"-----BEGIN PUBLIC KEY-----\n..."}`.
Neznámé kid, jiné algoritmy, jwk/jku, extra a duplicitní JSON klíče se odmítají.
Prázdné example keys záměrně neprojdou validací. Privátní signing key zůstává Staff.
Rotace: přidat nový veřejný klíč na SC, přepnout Staff kid, po doběhu starých
assertionů odebrat starý veřejný klíč. Povoleno je nejvýše 8 klíčů.

Ještě před vydáním lokálního grantu se atomicky zapíše hash issuer/audience/jti
do SQLite replay cache. Zápis přežije restart; expiruje až exp+5 sekund.
Podepsaný assertion nejde přes browser. Lokální jednorázový bearer spotřebuje
root auth adaptér; kořenová mapa pinující username i UID určí účet.
Cockpit session vzniká přes vlastní adaptér na upstream `[bearer] UnixPath`
protokolu, PAM account/session policy a skutečný upstream cockpit-bridge.
Staff podpis sám nevydává Cockpit cookie ani nepřiděluje root/sudo práva.

## Závislosti a testy

Opt-in SSO vyžaduje na Debianu `python3-cryptography` (API kompatibilní s řadou
38.x v Debianu 12). Instalátor sám nic přes APT nestahuje; chybějící import
zastaví spuštění před konfigurací. Theme samotná tuto závislost nepotřebuje.
Budoucí příprava prostředí: `sudo apt-get install python3-cryptography`.

Lokální testy: v izolovaném venv `python -m pip install cryptography==48.0.1`,
potom `python -m unittest discover -s tests -v`. GitHub workflow instaluje stejnou
testovací verzi. Privátní testovací Ed25519 klíče vznikají pouze v paměti.

Společný HTTP test: `python tests/integration_staff.py ../staff-center-sso`.
Staff fixture musí na prvním stdout řádku vrátit JSON `{origin,issuer,verification_keys}`;
origin je lokální HTTP URL, keys jsou veřejná PEM data. Fixture issuer je
`https://staff.diamondcrew.net`, service secret testovací `s` opakované 43krát.
Starý nepodepsaný fixture není kompatibilní a nesmí být uváděn jako úspěšný test.

## Opt-in skutečný Debian PAM/bridge test

Z root shellu v ověřovacím prostředí s odpovídající verzí a existujícím účtem:

```sh
python3 -B tests/debian_sso_integration.py --user skopy
```

Test vyžaduje Debian 12, Cockpit 287.1-0+deb12u3, cockpit-bridge a cryptography.
Použije dočasný Unix socket, SQLite a root-only mapu. Broker fixture běží jako
existující nobody; test nevytváří uživatele a nemění produkční konfiguraci,
PAM stack, skupiny ani služby. Otevře skutečnou PAM session a přes původní
cockpit-bridge stream channel porovná USER, real/effective/saved UID/GID a všechny
supplementary skupiny. Vyžaduje úspěšné pam_close_session a cleanup credentials.
Negativní scénáře: replay, expiry, neznámé Discord ID, změněný UID a root mapa.

PAM může vytvořit běžné audit/journal a logind/user-runtime události. Test uklidí
pouze vlastní procesy a dočasné soubory. Není to plný cockpit-ws/browser test:
cookie, heslový fallback, sudo/polkit, reálný Staff login a produkční proxy musí
projít zvláštním staging ověřením. Na Windows nativní test proveden nebyl.

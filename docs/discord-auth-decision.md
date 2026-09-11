# Výsledek analýzy Cockpit autentizace

Aktuální architektura je popsána v [sso.md](sso.md): Staff je jediný Discord OAuth
provider, Server Controller je relying party s lokálním Unix mapováním.

Upstream Cockpit 287.1 podporuje vlastní autentizační backend přes [bearer]
Command nebo UnixPath. Backend ověří externí identitu, otevře odpovídající Unix
relaci a spustí původní cockpit-bridge. Cockpit sám vydá session cookie.

Zdroj src/session/session.c má stejný princip pro Kerberos a TLS certifikáty:
perform_gssapi a perform_tlscert přecházejí po externím ověření do open_session
bez password pam_authenticate. Absence heslového PAM ověření proto sama o sobě
není technickou překážkou legitimní alternativní autentizace.

PAM account/session kontroly a Unix oprávnění je nutné zachovat samostatně.
Vlastní Staff adaptér není vestavěný upstream provider a vyžaduje Linux integrační
ověření. Původní návrh povinné gateway a samostatný Discord OAuth jsou nahrazeny.

Zdroje pro přesnou verzi:
- https://github.com/cockpit-project/cockpit/blob/287.1/doc/authentication.md
- https://github.com/cockpit-project/cockpit/blob/287.1/src/session/session.c
- https://github.com/cockpit-project/cockpit/blob/287.1/src/ws/cockpitauth.c
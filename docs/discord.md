# Discord login: nahrazeno centrálním Staff SSO

Aktuální postup je v [sso.md](sso.md). Server Controller již neimplementuje vlastní
Discord OAuth. Starý opt-in adapter z release 1.1.0 se nemá nově instalovat.
Pokud byl někde ručně aktivován, jeho odstranění musí provést původní installer
z jeho release před přechodem na Staff SSO. Automatická migrace secrets není.
(() => {
  'use strict';
  const status = document.getElementById('status');
  const command = args => cockpit.spawn(['/usr/bin/python3', '-B', '/usr/local/lib/dci-sso/accounts.py', ...args], {superuser: 'require', err: 'message'});
  const busy = value => document.querySelectorAll('button').forEach(button => { button.disabled = value; });
  async function refresh() {
    const data = JSON.parse(await command(['list']));
    const users = document.getElementById('user');
    users.replaceChildren(...data.users.map(name => { const option = document.createElement('option'); option.value = name; option.textContent = name; return option; }));
    const body = document.getElementById('links'); body.replaceChildren();
    for (const [id, account] of Object.entries(data.links)) {
      const row = document.createElement('tr');
      for (const value of [account.username, id]) { const cell = document.createElement('td'); cell.textContent = value; row.append(cell); }
      const cell = document.createElement('td'); const button = document.createElement('button'); button.textContent = 'Zrušit přiřazení';
      button.addEventListener('click', () => operate(async () => { await command(['unlink', '--user', account.username]); await refresh(); }));
      cell.append(button); row.append(cell); body.append(row);
    }
    document.getElementById('editor').hidden = false;
  }
  async function operate(action) {
    busy(true); status.textContent = '';
    try { await action(); } catch { status.textContent = 'Akce se nezdařila. Ověřte administrátorský přístup, instalaci Staff SSO a případné existující přiřazení.'; }
    finally { busy(false); }
  }
  document.getElementById('load').addEventListener('click', () => operate(refresh));
  document.getElementById('link-form').addEventListener('submit', event => {
    event.preventDefault();
    operate(async () => { await command(['link', '--user', document.getElementById('user').value, '--discord-id', document.getElementById('discord-id').value.trim()]); await refresh(); });
  });
})();

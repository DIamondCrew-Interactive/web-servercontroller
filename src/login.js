/* Discord token stays server-side. Browser receives only a one-use login ticket. */
(() => {
  'use strict';
  window.addEventListener('load', () => {
    if (!(document.documentElement.lang || navigator.language).toLowerCase().startsWith('cs')) return;
    for (const [selector, text] of Object.entries({
      '#login-button-text': 'Přihlásit se', '#show-other-login-options-text': 'Další možnosti',
      'label[for="login-user-input"]': 'Uživatelské jméno', 'label[for="login-password-input"]': 'Heslo',
      '#get-out-link': 'Zrušit'
    })) {
      document.querySelectorAll(selector).forEach(element => { element.textContent = text; });
    }
  });
  const ready = async () => {
    const button = document.getElementById('dci-discord-login');
    if (!button) return;
    const status = document.getElementById('dci-discord-status');
    const cs = (document.documentElement.lang || navigator.language).toLowerCase().startsWith('cs');
    button.textContent = cs ? 'Pokračovat přes Discord' : 'Continue with Discord';
    document.getElementById('dci-login-or').textContent = cs ? 'nebo' : 'or';
    button.addEventListener('click', event => {
      if (button.getAttribute('aria-disabled') === 'true') event.preventDefault();
    });
    const user = document.getElementById('user-group');
    const options = document.getElementById('dci-discord-options');
    const sync = () => { options.hidden = user.hidden; };
    new MutationObserver(sync).observe(user, {attributes: true, attributeFilter: ['hidden']});
    sync();
    try {
      const response = await fetch('/discord/status', {credentials: 'same-origin', cache: 'no-store'});
      if (!response.ok || !(await response.json()).enabled) throw new Error('unconfigured');
      button.removeAttribute('aria-disabled');
      button.href = '/discord/start';
      status.hidden = true;
      const redeem = await fetch('/discord/redeem', {method: 'POST', credentials: 'same-origin', headers: {'X-DCI-OAuth': '1'}});
      if (redeem.status === 204) return;
      if (!redeem.ok) throw new Error('redeem');
      const {ticket} = await redeem.json();
      if (typeof ticket !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(ticket)) throw new Error('ticket');
      const login = await fetch('cockpit/login', {method: 'GET', credentials: 'same-origin', headers: {'Authorization': 'Bearer ' + ticket}});
      if (!login.ok) {
        status.hidden = false;
        status.textContent = cs ? 'Discord není přiřazený k povolenému účtu, nebo přihlášení server odmítl.' : 'Discord is not linked to an eligible account, or the server refused login.';
        return;
      }
      window.location.replace('/');
    } catch {
      status.hidden = false;
      status.textContent = cs ? 'Přihlášení přes Discord není dostupné. Použijte účet serveru.' : 'Discord sign-in is unavailable. Use your server account.';
    }
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready);
  else ready();
})();

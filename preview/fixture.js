// Static fixture controls only. This script is never installed in Cockpit.
document.querySelector('form')?.addEventListener('submit', event => event.preventDefault());
document.querySelector('#login-button')?.addEventListener('click', () => {
  document.querySelector('#login-error-message').textContent = 'Preview only — authentication is disabled.';
  document.querySelector('#error-group').hidden = false;
});
document.querySelector('[data-open-dialog]')?.addEventListener('click', () => document.querySelector('dialog').showModal());
document.querySelector('[data-close-dialog]')?.addEventListener('click', () => document.querySelector('dialog').close());

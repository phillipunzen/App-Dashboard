'use strict';

(() => {
  const key = 'app-dashboard:theme-preference';
  const system = matchMedia('(prefers-color-scheme: dark)');
  const choices = ['auto', 'light', 'dark'];
  const labels = {auto: 'Automatisch (Geräteeinstellung)', light: 'Hell', dark: 'Dunkel'};
  const icons = {auto: 'monitor', light: 'sun', dark: 'moon'};
  let preference = 'auto';
  try {
    const saved = localStorage.getItem(key);
    if (choices.includes(saved)) preference = saved;
  } catch { /* Following the device does not require browser storage. */ }

  function apply() {
    const dark = preference === 'dark' || (preference === 'auto' && system.matches);
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    document.documentElement.dataset.themePreference = preference;
    document.querySelectorAll('[data-theme-toggle]').forEach((button) => {
      const next = choices[(choices.indexOf(preference) + 1) % choices.length];
      const label = `Design: ${labels[preference]}. Zu ${labels[next]} wechseln`;
      button.setAttribute('aria-label', label);
      button.title = label;
      button.querySelector('use').setAttribute('href', `/static/icons.svg#${icons[preference]}`);
    });
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? '#111b20' : '#f7f9fa');
  }
  function bind() {
    document.querySelectorAll('[data-theme-toggle]').forEach((button) => {
      button.addEventListener('click', () => {
        preference = choices[(choices.indexOf(preference) + 1) % choices.length];
        try { localStorage.setItem(key, preference); } catch { /* Preferences are optional. */ }
        apply();
      });
    });
    apply();
  }
  system.addEventListener('change', () => { if (preference === 'auto') apply(); });
  window.addEventListener('storage', (event) => {
    if (event.key === key || event.key === null) {
      preference = choices.includes(event.newValue) ? event.newValue : 'auto';
      apply();
    }
  });
  apply();
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind);
  else bind();
})();

'use strict';

const $ = (selector) => document.querySelector(selector);
const icon = (name) => `<svg aria-hidden="true"><use href="/static/icons.svg#${name}"/></svg>`;
const escapeHTML = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));
const storage = {
  get(key, fallback) { try { return JSON.parse(localStorage.getItem(`apphafen:${key}`)) ?? fallback; } catch { return fallback; } },
  set(key, value) { try { localStorage.setItem(`apphafen:${key}`, JSON.stringify(value)); } catch { /* Browser storage is optional. */ } },
};
const initialFavorites = storage.get('favorites', []);
const state = {
  apps: [], admin: false, csrf: '', loaded: false, filter: 'all', category: '', query: '', sort: 'name',
  view: storage.get('view', 'grid') === 'list' ? 'list' : 'grid',
  favorites: new Set(Array.isArray(initialFavorites) ? initialFavorites.filter(Number.isInteger) : []),
  editing: null, formIcon: undefined, color: 'teal', afterLogin: null, metadataController: null,
};
const colors = {teal: 'Grün', blue: 'Blau', purple: 'Violett', orange: 'Orange', rose: 'Rosa', slate: 'Grau'};
const germanSort = new Intl.Collator('de', {sensitivity: 'base', numeric: true});

async function api(path, {method = 'GET', data, signal} = {}) {
  const response = await fetch(path, {
    method, signal, credentials: 'same-origin',
    headers: {'Content-Type': 'application/json', ...(method !== 'GET' ? {'X-CSRF-Token': state.csrf} : {})},
    ...(data !== undefined ? {body: JSON.stringify(data)} : {}),
  });
  if (response.status === 204) return null;
  let body;
  try { body = await response.json(); } catch { throw new Error('Der Server ist gerade nicht erreichbar. Bitte versuche es erneut.'); }
  if (!response.ok) {
    const error = new Error(body.error || 'Die Anfrage konnte nicht verarbeitet werden.');
    error.status = response.status;
    throw error;
  }
  return body;
}
function toast(message) {
  const element = document.createElement('div');
  element.className = 'toast';
  element.innerHTML = icon('check') + `<span>${escapeHTML(message)}</span>`;
  $('#toast-container').append(element);
  setTimeout(() => element.remove(), 4200);
}
function setError(selector, error) {
  const element = $(selector);
  element.textContent = error ? error.message || error : '';
  element.hidden = !error;
}
function closeDialogs() { document.querySelectorAll('dialog[open]').forEach((dialog) => dialog.close()); }
function updateSidebarVisibility() {
  const mobile = matchMedia('(max-width: 600px)').matches;
  const open = mobile && $('#sidebar').classList.contains('open');
  $('#sidebar').inert = mobile && !open;
  $('#sidebar-overlay').hidden = !open;
}
function closeSidebar() {
  $('#sidebar').classList.remove('open');
  $('#mobile-menu').setAttribute('aria-expanded', 'false');
  updateSidebarVisibility();
}
function showDialog(selector) {
  closeSidebar();
  const dialog = $(selector);
  if (!dialog.open) dialog.showModal();
}
function openLogin(callback = null) {
  closeDialogs();
  state.afterLogin = callback;
  $('#password').value = '';
  $('#password').type = 'password';
  $('#show-password').setAttribute('aria-label', 'Passwort anzeigen');
  setError('#login-error', null);
  showDialog('#login-dialog');
  if ($('#username').value) $('#password').focus();
}
function updateAdmin() {
  $('#admin-label').textContent = state.admin ? 'Admin angemeldet' : 'Verwaltung';
  $('#admin-status').textContent = state.admin ? 'Sammlung verwalten' : 'Als Admin anmelden';
}
function categories() {
  return [...new Set(state.apps.map((app) => app.category).filter(Boolean))].sort(germanSort.compare);
}
function changeFilter(filter, category = '') {
  state.filter = filter;
  state.category = category;
  $('#category-select').value = category;
  closeSidebar();
  render();
}
function resetFilters() {
  state.query = '';
  $('#search-input').value = '';
  changeFilter('all');
}
function initials(name) {
  return (name.trim().split(/\s+/).map((part) => [...part][0]).slice(0, 2).join('') || 'A').toLocaleUpperCase('de');
}
function appIcon(app) {
  return `<span class="app-icon ${escapeHTML(app.color)}">${app.icon_url ? `<img src="${escapeHTML(app.icon_url)}" alt="" loading="lazy">` : escapeHTML(initials(app.name))}</span>`;
}
function cardHTML(app) {
  const favorite = state.favorites.has(app.id);
  let host;
  try { host = new URL(app.url).host; } catch { host = app.url; }
  return `<article class="app-card"><a class="card-link" href="${escapeHTML(app.url)}" target="_blank" rel="noopener noreferrer" aria-label="${escapeHTML(app.name)} in neuem Tab öffnen"><div class="card-top">${appIcon(app)}</div><h3>${escapeHTML(app.name)}</h3><p class="app-description">${escapeHTML(app.description || 'Deine Anwendung – mit einem Klick erreichbar.')}</p><div class="card-meta"><span class="category-pill">${escapeHTML(app.category || 'Allgemein')}</span><span class="card-host"><span>${escapeHTML(host)}</span>${icon('external')}</span></div></a><div class="card-actions"><button class="icon-button favorite-button ${favorite ? 'is-favorite' : ''}" data-favorite="${app.id}" aria-label="${escapeHTML(app.name)} ${favorite ? 'aus Favoriten entfernen' : 'zu Favoriten hinzufügen'}" aria-pressed="${favorite}" title="${favorite ? 'Aus Favoriten entfernen' : 'Als Favorit merken'}">${icon('star')}</button>${state.admin ? `<button class="icon-button edit-button" data-edit="${app.id}" aria-label="${escapeHTML(app.name)} bearbeiten" title="App bearbeiten">${icon('edit')}</button>` : ''}</div></article>`;
}
function render() {
  if (!state.loaded) return;
  const cats = categories();
  const validIds = new Set(state.apps.map((app) => app.id));
  state.favorites = new Set([...state.favorites].filter((id) => validIds.has(id)));
  storage.set('favorites', [...state.favorites]);
  const total = state.apps.length;
  for (const selector of ['#nav-total', '#stat-total']) $(selector).textContent = total;
  for (const selector of ['#nav-favorites', '#stat-favorites']) $(selector).textContent = state.favorites.size;
  for (const selector of ['#category-count', '#stat-categories']) $(selector).textContent = cats.length;
  $('#no-categories').hidden = cats.length > 0;
  $('#category-nav').innerHTML = cats.map((category, index) => `<button class="nav-item ${state.category === category ? 'active' : ''}" data-category="${escapeHTML(category)}"><span class="category-dot ${Object.keys(colors)[index % 6]}"></span><span class="category-name">${escapeHTML(category)}</span><span class="nav-count">${state.apps.filter((app) => app.category === category).length}</span></button>`).join('');
  if (state.category && !cats.includes(state.category)) { state.category = ''; state.filter = 'all'; }
  const selectValue = state.category;
  $('#category-select').innerHTML = '<option value="">Alle Kategorien</option>' + cats.map((category) => `<option value="${escapeHTML(category)}">${escapeHTML(category)}</option>`).join('');
  $('#category-select').value = selectValue;
  $('#category-options').innerHTML = cats.map((category) => `<option value="${escapeHTML(category)}"></option>`).join('');
  document.querySelectorAll('[data-filter]').forEach((button) => button.classList.toggle('active', button.dataset.filter === state.filter && !state.category));
  const label = state.category || (state.filter === 'favorites' ? 'Favoriten' : 'Alle Apps');
  $('#breadcrumb-label').textContent = label;
  // Keep the count element separate so category names remain plain text.
  $('#collection-title').firstChild.textContent = label + ' ';
  $('#collection-subtitle').textContent = state.filter === 'favorites' ? 'Deine schnellen Wege. Persönlich in diesem Browser gespeichert.' : state.category ? 'Alles aus dieser Kategorie auf einen Blick.' : 'Deine Sammlung, dein Überblick.';
  const query = state.query.toLocaleLowerCase('de').trim();
  const apps = state.apps.filter((app) =>
    (state.filter !== 'favorites' || state.favorites.has(app.id)) &&
    (!state.category || app.category === state.category) &&
    (!query || [app.name, app.description, app.url, app.category].join(' ').toLocaleLowerCase('de').includes(query))
  );
  apps.sort((a, b) => state.sort === 'newest' ? b.created_at.localeCompare(a.created_at) || b.id - a.id : state.sort === 'oldest' ? a.created_at.localeCompare(b.created_at) || a.id - b.id : germanSort.compare(a.name, b.name));
  $('#result-count').textContent = apps.length;
  $('#loading').hidden = true;
  $('#error-state').hidden = true;
  $('#empty-state').hidden = total > 0;
  $('#getting-started').hidden = total > 0;
  $('#no-results').hidden = total === 0 || apps.length > 0;
  const noFavorites = state.filter === 'favorites' && !state.favorites.size && !query && !state.category;
  $('#no-results-title').textContent = noFavorites ? 'Deine Lieblingsapps sind nur einen Stern entfernt.' : 'Keine Apps gefunden';
  $('#no-results-description').textContent = noFavorites ? 'Markiere eine App mit dem Stern, um sie hier wiederzufinden.' : 'Versuche einen anderen Suchbegriff oder passe die Filter an.';
  $('#app-grid').classList.toggle('list-view', state.view === 'list');
  $('#grid-view').classList.toggle('active', state.view === 'grid');
  $('#list-view').classList.toggle('active', state.view === 'list');
  $('#grid-view').setAttribute('aria-pressed', state.view === 'grid');
  $('#list-view').setAttribute('aria-pressed', state.view === 'list');
  $('#app-grid').innerHTML = apps.map(cardHTML).join('') + (total && state.filter === 'all' && !query ? `<button class="add-card" data-action="add"><span class="add-card-icon">${icon('plus')}</span>Eine weitere App hinzufügen<small>Deine Sammlung wächst mit dir.</small></button>` : '');
  $('#app-grid').querySelectorAll('img').forEach((img) => img.addEventListener('error', () => {
    const app = state.apps.find((item) => item.id === Number(img.closest('.app-card').querySelector('[data-favorite]').dataset.favorite));
    img.parentElement.textContent = initials(app?.name || 'A');
  }, {once: true}));
}
async function load() {
  $('#loading').hidden = false;
  $('#error-state').hidden = true;
  try {
    const [sessionData, appsData] = await Promise.all([api('/api/session'), api('/api/apps')]);
    state.admin = sessionData.admin;
    state.csrf = sessionData.csrf;
    state.apps = appsData.apps;
    state.loaded = true;
    updateAdmin();
    render();
  } catch (error) {
    $('#loading').hidden = true;
    $('#error-state').hidden = false;
    $('#error-message').textContent = error.message;
  }
}
function previewIcon() {
  const preview = $('#icon-preview');
  preview.className = `app-icon ${state.color}`;
  preview.replaceChildren();
  const src = state.formIcon ? `data:image/png;base64,${state.formIcon}` : state.formIcon === undefined ? state.editing?.icon_url : null;
  if (src) { const img = document.createElement('img'); img.src = src; img.alt = ''; preview.append(img); }
  else preview.textContent = initials($('#app-name').value || 'App');
  $('#remove-icon').hidden = !src;
}
function selectColor(color) {
  state.color = Object.hasOwn(colors, color) ? color : 'teal';
  $('#color-options').innerHTML = Object.entries(colors).map(([value, label]) => `<label class="color-option" title="${label}"><input type="radio" name="color" value="${value}" aria-label="${label}" ${state.color === value ? 'checked' : ''}><span class="${value}"></span></label>`).join('');
  previewIcon();
}
function openApp(app = null) {
  if (!state.admin) { openLogin(() => openApp(app)); return; }
  state.metadataController?.abort();
  state.metadataController = null;
  closeDialogs();
  state.editing = app;
  state.formIcon = undefined;
  $('#app-form').reset();
  $('#icon-upload').value = '';
  $('#app-dialog-title').textContent = app ? 'App bearbeiten.' : 'Ein neuer Ankerplatz.';
  $('#app-dialog .modal-description').textContent = app ? 'Passe den Eintrag so an, wie er zu dir passt.' : 'Füge eine App hinzu. Alles beginnt mit einem Link.';
  $('#app-url').value = app?.url || '';
  $('#app-name').value = app?.name || '';
  $('#app-description').value = app?.description || '';
  $('#app-category').value = app?.category || (state.category || '');
  $('#delete-app').hidden = !app;
  $('#save-app').disabled = false;
  $('#fetch-metadata').disabled = false;
  $('#fetch-metadata').innerHTML = icon('sparkles') + '<span>Details laden</span>';
  $('#metadata-message').className = 'field-hint';
  $('#metadata-message').textContent = 'Logo, Name und Beschreibung automatisch vorschlagen lassen.';
  setError('#app-error', null);
  selectColor(app?.color || 'teal');
  showDialog('#app-dialog');
}
async function fetchMetadata() {
  const url = $('#app-url').value.trim();
  if (!url || state.metadataController) return;
  setError('#app-error', null);
  const controller = new AbortController();
  state.metadataController = controller;
  const oldName = $('#app-name').value;
  const oldDescription = $('#app-description').value;
  $('#fetch-metadata').disabled = true;
  $('#save-app').disabled = true;
  $('#fetch-metadata').innerHTML = '<span class="spinner"></span><span>Wird geladen …</span>';
  $('#metadata-message').className = 'field-hint';
  $('#metadata-message').textContent = 'Wir suchen Name, Beschreibung und Favicon für dich …';
  const timeout = setTimeout(() => controller.abort(), 25000);
  try {
    const data = await api('/api/metadata', {method: 'POST', data: {url}, signal: controller.signal});
    if ($('#app-url').value.trim() !== url || !$('#app-dialog').open) return;
    $('#app-url').value = data.url;
    if ($('#app-name').value === oldName) $('#app-name').value = data.name;
    if ($('#app-description').value === oldDescription) $('#app-description').value = data.description;
    if (data.icon) state.formIcon = data.icon;
    previewIcon();
    $('#metadata-message').textContent = data.warning || 'Details gefunden. Du kannst alles nach deinem Geschmack anpassen.';
    $('#metadata-message').className = 'field-hint ' + (data.warning ? 'warning' : 'success');
  } catch (error) {
    if ($('#app-dialog').open) {
      $('#metadata-message').textContent = error.name === 'AbortError' ? 'Der Abruf dauert zu lange. Du kannst die Details manuell eingeben.' : error.message;
      $('#metadata-message').className = 'field-hint warning';
    }
  } finally {
    clearTimeout(timeout);
    if (state.metadataController === controller) {
      state.metadataController = null;
      $('#fetch-metadata').disabled = false;
      $('#save-app').disabled = false;
      $('#fetch-metadata').innerHTML = icon('sparkles') + '<span>Details laden</span>';
    }
  }
}

// Personal display preferences never change the shared collection.
$('#mobile-menu').addEventListener('click', () => {
  const open = $('#sidebar').classList.toggle('open');
  $('#mobile-menu').setAttribute('aria-expanded', open);
  updateSidebarVisibility();
  if (open) $('#sidebar .nav-item').focus();
});
matchMedia('(max-width: 600px)').addEventListener('change', updateSidebarVisibility);
updateSidebarVisibility();
document.addEventListener('click', (event) => {
  const add = event.target.closest('[data-action="add"]');
  if (add) { openApp(); return; }
  const close = event.target.closest('[data-close]');
  if (close) { close.closest('dialog').close(); return; }
  const filter = event.target.closest('[data-filter]');
  if (filter) { changeFilter(filter.dataset.filter); return; }
  const category = event.target.closest('[data-category]');
  if (category) { changeFilter('all', category.dataset.category); return; }
  const favorite = event.target.closest('[data-favorite]');
  if (favorite) {
    const id = Number(favorite.dataset.favorite);
    const wasFavorite = state.favorites.has(id);
    wasFavorite ? state.favorites.delete(id) : state.favorites.add(id);
    render();
    toast(wasFavorite ? 'Aus deinen Favoriten entfernt.' : 'In deinen Favoriten gespeichert.');
    $('#app-grid').querySelector(`[data-favorite="${id}"]`)?.focus({preventScroll: true});
    return;
  }
  const edit = event.target.closest('[data-edit]');
  if (edit) { openApp(state.apps.find((app) => app.id === Number(edit.dataset.edit))); return; }
  if ($('#sidebar').classList.contains('open') && !event.target.closest('#sidebar, #mobile-menu')) closeSidebar();
});
document.addEventListener('keydown', (event) => {
  const input = /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName);
  if (event.key === '/' && !input && !document.querySelector('dialog[open]')) { event.preventDefault(); $('#search-input').focus(); }
  if (event.key === 'Escape' && $('#sidebar').classList.contains('open')) { closeSidebar(); $('#mobile-menu').focus(); }
});
document.querySelectorAll('dialog').forEach((dialog) => {
  dialog.addEventListener('click', (event) => { if (event.target === dialog) { const r = dialog.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close(); } });
});
$('#app-dialog').addEventListener('close', () => { state.metadataController?.abort(); state.metadataController = null; });
$('#search-input').addEventListener('input', (event) => { state.query = event.target.value; render(); });
$('#category-select').addEventListener('change', (event) => { state.category = event.target.value; render(); });
$('#sort-select').addEventListener('change', (event) => { state.sort = event.target.value; render(); });
$('#grid-view').addEventListener('click', () => { state.view = 'grid'; storage.set('view', 'grid'); render(); });
$('#list-view').addEventListener('click', () => { state.view = 'list'; storage.set('view', 'list'); render(); });
$('#reset-filters').addEventListener('click', resetFilters);
$('#retry-button').addEventListener('click', load);
$('#admin-button').addEventListener('click', () => state.admin ? showDialog('#admin-dialog') : openLogin());
$('#show-password').addEventListener('click', () => {
  const reveal = $('#password').type === 'password';
  $('#password').type = reveal ? 'text' : 'password';
  $('#show-password').setAttribute('aria-label', reveal ? 'Passwort verbergen' : 'Passwort anzeigen');
});
$('#login-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  setError('#login-error', null);
  $('#login-submit').disabled = true;
  try {
    const data = await api('/api/login', {method: 'POST', data: {username: $('#username').value, password: $('#password').value}});
    state.admin = data.admin;
    state.csrf = data.csrf;
    $('#password').value = '';
    $('#login-dialog').close();
    updateAdmin(); render();
    toast('Du bist jetzt als Admin angemeldet.');
    const callback = state.afterLogin;
    state.afterLogin = null;
    if (callback) callback();
  } catch (error) { setError('#login-error', error); }
  finally { $('#login-submit').disabled = false; }
});
$('#logout-button').addEventListener('click', async () => {
  $('#logout-button').disabled = true;
  try {
    const data = await api('/api/logout', {method: 'POST'});
    state.admin = false; state.csrf = data.csrf;
    closeDialogs(); updateAdmin(); render();
    toast('Du bist abgemeldet.');
  } catch (error) { toast(error.message); }
  finally { $('#logout-button').disabled = false; }
});
$('#fetch-metadata').addEventListener('click', fetchMetadata);
$('#app-url').addEventListener('change', () => { if (!state.editing && !$('#app-name').value.trim()) fetchMetadata(); });
$('#app-name').addEventListener('input', previewIcon);
$('#color-options').addEventListener('change', (event) => { state.color = event.target.value; previewIcon(); });
$('#remove-icon').addEventListener('click', () => { state.formIcon = null; $('#icon-upload').value = ''; previewIcon(); });
$('#icon-upload').addEventListener('change', async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  setError('#app-error', null);
  if (file.size > 256000) { setError('#app-error', 'Das Logo darf maximal 250 KB groß sein.'); event.target.value = ''; return; }
  try {
    const data = await new Promise((resolve, reject) => {
      const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.onerror = reject; reader.readAsDataURL(file);
    });
    const img = new Image();
    img.src = data;
    await img.decode();
    const canvas = document.createElement('canvas');
    const scale = Math.min(1, 192 / img.naturalWidth, 192 / img.naturalHeight);
    canvas.width = Math.max(1, Math.round(img.naturalWidth * scale));
    canvas.height = Math.max(1, Math.round(img.naturalHeight * scale));
    canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
    state.formIcon = canvas.toDataURL('image/png').split(',')[1];
    previewIcon();
  } catch { setError('#app-error', 'Dieses Bild konnte nicht gelesen werden. Bitte verwende ein anderes Logo.'); }
});
$('#app-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  setError('#app-error', null);
  $('#save-app').disabled = true;
  const editing = state.editing;
  const data = {url: $('#app-url').value, name: $('#app-name').value, description: $('#app-description').value, category: $('#app-category').value, color: state.color};
  if (state.formIcon !== undefined) data.icon = state.formIcon;
  try {
    const result = await api(editing ? `/api/apps/${editing.id}` : '/api/apps', {method: editing ? 'PUT' : 'POST', data});
    state.apps = state.apps.filter((app) => app.id !== result.app.id).concat(result.app);
    $('#app-dialog').close(); render();
    toast(editing ? 'App aktualisiert.' : `${result.app.name} hat einen neuen Ankerplatz.`);
  } catch (error) { setError('#app-error', error); }
  finally { $('#save-app').disabled = false; }
});
$('#delete-app').addEventListener('click', () => {
  if (!state.editing) return;
  $('#delete-description').textContent = `„${state.editing.name}“ wird aus der Sammlung entfernt. Die Anwendung selbst bleibt erhalten.`;
  setError('#delete-error', null);
  showDialog('#delete-dialog');
});
$('#confirm-delete').addEventListener('click', async () => {
  if (!state.editing) return;
  const id = state.editing.id;
  $('#confirm-delete').disabled = true;
  try {
    await api(`/api/apps/${id}`, {method: 'DELETE'});
    state.apps = state.apps.filter((app) => app.id !== id);
    closeDialogs(); render(); toast('App aus der Sammlung entfernt.');
  } catch (error) { setError('#delete-error', error); }
  finally { $('#confirm-delete').disabled = false; }
});
load();

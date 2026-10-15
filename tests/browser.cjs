// Run against a disposable, empty test instance, never against an existing collection.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const url = process.env.APPHAFEN_TEST_URL || 'http://127.0.0.1:8131';
const password = process.env.APPHAFEN_TEST_PASSWORD;
if (!password) throw new Error('APPHAFEN_TEST_PASSWORD must be set for a disposable test instance.');

(async () => {
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  const context = await browser.newContext({viewport: {width: 1440, height: 1100}, colorScheme: 'light'});
  const page = await context.newPage();
  const errors = [];
  const createdIds = new Set();
  page.on('pageerror', (error) => errors.push(error.message));
  try {
    const initial = await (await context.request.get(url + '/api/apps')).json();
    assert.deepEqual(initial.apps, [], 'Browser checks require an empty, disposable test instance.');
    await page.goto(url + '/admin');
    await page.locator('#empty-state').waitFor({state: 'visible'});
    await fs.mkdir('artifacts', {recursive: true});
    await page.screenshot({path: 'artifacts/empty-desktop.png', fullPage: true});
    await page.getByRole('button', {name: 'Erste App hinzufügen', exact: true}).click();
    await page.locator('#login-dialog').waitFor({state: 'visible'});
    await page.locator('#password').fill(password);
    await page.locator('#login-submit').click();
    await page.locator('#app-dialog').waitFor({state: 'visible'});
    await page.route('**/api/metadata', async (route) => {
      const data = route.request().postDataJSON();
      await route.fulfill({json: {url: data.url, name: 'Nextcloud', description: 'Dateien, Kalender und Kontakte. Deine persönliche Cloud, jederzeit erreichbar.', icon: null, warning: null}});
    });
    await page.locator('#app-url').fill('https://cloud.example.de');
    await page.locator('#app-url').press('Tab');
    await page.waitForFunction(() => document.querySelector('#app-name').value === 'Nextcloud');
    await page.locator('#app-category').fill('Produktivität');
    const createdResponse = page.waitForResponse((response) => response.url().endsWith('/api/apps') && response.request().method() === 'POST' && response.status() === 201);
    await page.locator('#save-app').click();
    createdIds.add((await (await createdResponse).json()).app.id);
    await page.locator('#app-dialog').waitFor({state: 'hidden'});
    await page.getByRole('link', {name: 'Nextcloud in neuem Tab öffnen', exact: true}).waitFor();
    await page.locator('[data-favorite]').first().click();
    await page.locator('[data-filter="favorites"]').click();
    assert.equal(await page.locator('.app-card').count(), 1);
    assert.equal(await page.locator('#stat-favorites').textContent(), '1');
    await page.locator('[data-filter="all"]').click();
    await page.locator('[data-edit]').first().click();
    await page.locator('#app-name').fill('Meine Nextcloud');
    await page.locator('#icon-upload').setInputFiles({name: 'logo.png', mimeType: 'image/png', buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAIAAABvFaqvAAAAIklEQVR4nGPkqC9moAZgooopowaNGjRq0KhBowaNGkQRAABYEgEqeGm2MwAAAABJRU5ErkJggg==', 'base64')});
    await page.waitForFunction(() => document.querySelector('#icon-preview img')?.complete);
    await page.locator('#save-app').click();
    await page.locator('#app-dialog').waitFor({state: 'hidden'});
    await page.getByRole('link', {name: 'Meine Nextcloud in neuem Tab öffnen', exact: true}).waitFor();
    assert.equal(await page.getByRole('link', {name: 'Meine Nextcloud in neuem Tab öffnen', exact: true}).locator('img').count(), 1);
    const demo = [
      ['Grafana', 'https://grafana.example.de', 'Metriken und Dashboards für einen klaren Blick auf deine Infrastruktur.', 'Monitoring', 'orange'],
      ['Paperless-ngx', 'https://paperless.example.de', 'Deine Dokumente digital organisiert. Finden statt abheften.', 'Produktivität', 'teal'],
      ['Home Assistant', 'https://home.example.de', 'Licht, Klima und Automationen. Dein Zuhause in deiner Hand.', 'Smart Home', 'blue'],
      ['Gitea', 'https://git.example.de', 'Ein Zuhause für deinen Code, deine Projekte und die nächste gute Idee.', 'Entwicklung', 'purple'],
      ['Vaultwarden', 'https://vault.example.de', 'Passwörter und sensible Daten an einem sicheren Platz.', 'Sicherheit', 'slate'],
      ['Portainer', 'https://portainer.example.de', 'Container, Stacks und Docker-Umgebungen einfach verwalten.', 'Infrastruktur', 'blue'],
    ];
    const demoIds = await page.evaluate(async (records) => {
      const ids = [];
      const session = await (await fetch('/api/session')).json();
      for (const [name, url, description, category, color] of records) {
        const result = await fetch('/api/apps', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': session.csrf}, body: JSON.stringify({name, url, description, category, color})});
        if (!result.ok) throw new Error(await result.text());
        ids.push((await result.json()).app.id);
      }
      return ids;
    }, demo);
    demoIds.forEach((id) => createdIds.add(id));
    // The public page stays minimal, including while an admin session exists.
    const visitor = await context.newPage();
    visitor.on('pageerror', (error) => errors.push(error.message));
    await visitor.setViewportSize({width: 1440, height: 1000});
    await visitor.goto(url);
    assert.equal(await visitor.locator('.app').count(), 7);
    assert.equal(await visitor.locator('#sidebar, .stats, [data-action="add"], [data-edit], dialog').count(), 0);
    assert.equal(await visitor.getByRole('link', {name: 'Meine Nextcloud in neuem Tab öffnen', exact: true}).getAttribute('target'), '_blank');
    assert.match(await visitor.title(), /App Dashboard/);
    assert.equal(await visitor.locator('html').getAttribute('data-theme-preference'), 'auto');
    const info = visitor.getByRole('button', {name: 'Infos zu Meine Nextcloud', exact: true});
    const app = info.locator('..');
    const compactWidth = (await app.boundingBox()).width;
    assert.ok((await app.boundingBox()).height < 140, 'Desktop tiles should be compact');
    await info.click();
    assert.equal(await info.getAttribute('aria-expanded'), 'true');
    assert.ok((await app.boundingBox()).width > compactWidth * 1.5, 'Info expands the tile');
    assert.equal(await app.locator('.app-details').getAttribute('hidden'), null);
    assert.match(await app.locator('.app-details p').textContent(), /Dateien, Kalender/);
    assert.equal(await app.locator('.detail-open').getAttribute('href'), 'https://cloud.example.de/');
    assert.equal(visitor.url(), url + '/');
    await visitor.screenshot({path: 'artifacts/user-dashboard-expanded.png', fullPage: true});
    await visitor.keyboard.press('Escape');
    assert.equal(await info.getAttribute('aria-expanded'), 'false');
    await info.focus();
    await visitor.keyboard.press('Enter');
    assert.equal(await info.getAttribute('aria-expanded'), 'true');
    await visitor.getByRole('button', {name: 'Infos zu Grafana', exact: true}).click();
    assert.equal(await visitor.locator('.is-expanded').count(), 1);
    assert.equal(await info.getAttribute('aria-expanded'), 'false');
    await visitor.keyboard.press('Escape');
    await visitor.evaluate(() => document.activeElement.blur());
    await visitor.mouse.move(0, 0);
    await visitor.waitForTimeout(250);
    await visitor.screenshot({path: 'artifacts/user-dashboard-desktop.png', fullPage: true});
    await visitor.emulateMedia({colorScheme: 'dark'});
    await visitor.waitForFunction(() => document.documentElement.dataset.theme === 'dark');
    await visitor.waitForTimeout(250);
    await visitor.screenshot({path: 'artifacts/user-dashboard-dark.png', fullPage: true});
    await visitor.getByRole('button', {name: /Design: Automatisch/}).click();
    assert.equal(await visitor.locator('html').getAttribute('data-theme'), 'light');
    await visitor.reload();
    assert.equal(await visitor.locator('html').getAttribute('data-theme'), 'light');
    await visitor.getByRole('button', {name: /Design: Hell/}).click();
    assert.equal(await visitor.locator('html').getAttribute('data-theme'), 'dark');
    await visitor.emulateMedia({colorScheme: 'light'});
    assert.equal(await visitor.locator('html').getAttribute('data-theme'), 'dark');
    await visitor.getByRole('button', {name: /Design: Dunkel/}).click();
    assert.equal(await visitor.locator('html').getAttribute('data-theme-preference'), 'auto');
    await visitor.waitForFunction(() => document.documentElement.dataset.theme === 'light');
    await visitor.locator('#app-search').fill('Docker');
    assert.equal(await visitor.locator('.app:visible').count(), 1);
    assert.match(await visitor.locator('.app:visible h2').textContent(), /Portainer/);
    await visitor.locator('#app-search').fill('unbekannte-app-12345');
    await visitor.locator('#no-results').waitFor({state: 'visible'});
    await visitor.locator('#app-search').fill('');
    for (const width of [375, 390, 768, 1024, 1440]) {
      await visitor.setViewportSize({width, height: 900});
      assert.equal(await visitor.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `Public page overflow at ${width}px`);
    }
    await visitor.setViewportSize({width: 390, height: 844});
    await visitor.screenshot({path: 'artifacts/user-dashboard-mobile.png', fullPage: true});
    await visitor.emulateMedia({colorScheme: 'dark'});
    await visitor.waitForFunction(() => document.documentElement.dataset.theme === 'dark');
    await visitor.getByRole('button', {name: 'Infos zu Grafana', exact: true}).click();
    assert.equal(await visitor.locator('.is-expanded').count(), 1);
    assert.equal(await visitor.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await visitor.screenshot({path: 'artifacts/user-dashboard-mobile-dark.png', fullPage: true});
    await visitor.emulateMedia({colorScheme: 'light'});
    await visitor.close();

    await page.reload();
    await page.waitForFunction(() => document.querySelectorAll('.app-card').length === 7);
    await page.locator('#search-input').fill('Docker');
    await page.waitForFunction(() => document.querySelectorAll('.app-card').length === 1);
    assert.match(await page.locator('.app-card h3').textContent(), /Portainer/);
    await page.locator('#search-input').fill('unbekannte-app-12345');
    await page.locator('#no-results').waitFor({state: 'visible'});
    await page.locator('#reset-filters').click();
    await page.locator('#category-select').selectOption('Produktivität');
    assert.equal(await page.locator('.app-card').count(), 2);
    await page.locator('#category-select').selectOption('');
    await page.locator('#list-view').click();
    assert.match(await page.locator('#app-grid').getAttribute('class'), /list-view/);
    await page.screenshot({path: 'artifacts/list-desktop.png', fullPage: true});
    await page.locator('#grid-view').click();
    await page.screenshot({path: 'artifacts/dashboard-desktop.png', fullPage: true});
    await page.locator('#theme-button').click(); // Automatic -> light
    await page.locator('#theme-button').click(); // Light -> dark
    assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark');
    await page.waitForTimeout(250);
    await page.screenshot({path: 'artifacts/dashboard-dark.png', fullPage: true});
    await page.locator('#theme-button').click();
    for (const width of [375, 390, 768, 1024, 1440]) {
      await page.setViewportSize({width, height: 1000});
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
      assert.equal(overflow, false, `Unexpected horizontal overflow at ${width}px`);
    }
    await page.setViewportSize({width: 390, height: 844});
    await page.waitForTimeout(250);
    await page.screenshot({path: 'artifacts/dashboard-mobile.png', fullPage: true});
    await page.locator('#mobile-menu').click();
    await page.locator('#admin-button').click();
    await page.locator('#admin-dialog').waitFor({state: 'visible'});
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('link', {name: 'Sammlung als JSON exportieren'}).click();
    const download = await downloadPromise;
    assert.equal(download.suggestedFilename(), 'apphafen-export.json');
    await page.locator('#logout-button').click();
    await page.locator('#admin-dialog').waitFor({state: 'hidden'});
    assert.equal(await page.locator('[data-edit]').count(), 0);
    assert.equal(await page.locator('#stat-favorites').textContent(), '1');
    await page.locator('#mobile-menu').click();
    await page.locator('#admin-button').click();
    await page.locator('#password').fill(password);
    await page.locator('#login-submit').click();
    await page.locator('#login-dialog').waitFor({state: 'hidden'});
    await page.locator('[data-edit]').first().click();
    await page.locator('#delete-app').click();
    await page.locator('#delete-dialog').waitFor({state: 'visible'});
    await page.locator('#confirm-delete').click();
    await page.locator('#delete-dialog').waitFor({state: 'hidden'});
    assert.equal(await page.locator('.app-card').count(), 6);
    await page.setViewportSize({width: 375, height: 812});
    await page.locator('.topbar [data-action="add"]').click();
    await page.locator('#app-dialog').waitFor({state: 'visible'});
    assert.equal(await page.evaluate(() => document.querySelector('#app-dialog').scrollWidth > document.querySelector('#app-dialog').clientWidth), false, 'Modal has horizontal overflow');
    await page.screenshot({path: 'artifacts/add-mobile.png', fullPage: true});
    await page.locator('#app-dialog [data-close]').first().click();
    assert.deepEqual(errors, [], 'JavaScript errors');
    console.log('Browser checks passed: login, metadata autofill, CRUD, favorites, search, categories, grid/list, system theme changes, manual theme preferences, compact tiles, expandable details, export, logout and responsive layouts.');
  } finally {
    // Remove only test entries so a rerun starts empty.
    await page.evaluate(async (ids) => {
      const session = await (await fetch('/api/session')).json();
      if (!session.admin) return;
      for (const id of ids) await fetch(`/api/apps/${id}`, {method: 'DELETE', headers: {'X-CSRF-Token': session.csrf}});
    }, [...createdIds]).catch(() => {});
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exit(1); });

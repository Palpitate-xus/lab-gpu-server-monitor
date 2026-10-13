const { test, expect } = require('@playwright/test');
const { payload, admin } = require('./layout-fixtures.cjs');

const paths = ['/cockpit', '/dashboard', '/servers', '/servers/1', '/gpu-analysis',
  '/gpu-matrix', '/reports', '/alerts', '/users', '/settings', '/help',
  '/account/password', '/mfa-setup', '/status', '/login', '/not-found-layout'];

async function isolate(page, mode) {
  const auth = { user: admin };
  await page.addInitScript(theme => localStorage.setItem('theme-mode', theme), mode);
  // No request can reach real API data, SSH actions, secrets or notifications.
  await page.route('**/api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/auth/me' && auth.user === null) {
      return route.fulfill({ status: 401, json: { detail: 'Unauthenticated layout fixture' } });
    }
    return route.fulfill({ status: 200, json: payload(path, auth.user) });
  });
  return auth;
}

async function open(page, path) {
  await page.goto(path, { waitUntil: 'networkidle' });
  await expect(page.locator('#app')).not.toBeEmpty();
}

async function sameRow(page, selector, count) {
  const positions = await page.locator(selector).evaluateAll(nodes => nodes.map(node => {
    const rect = node.getBoundingClientRect();
    return { top: rect.top, height: rect.height };
  }));
  expect(positions.length).toBeGreaterThanOrEqual(count);
  expect(Math.max(...positions.slice(0, count).map(r => r.top)) -
    Math.min(...positions.slice(0, count).map(r => r.top))).toBeLessThan(1);
  expect(Math.max(...positions.slice(0, count).map(r => r.height)) -
    Math.min(...positions.slice(0, count).map(r => r.height))).toBeLessThan(1);
}

test('all routes render without runtime errors or viewport overflow', async ({ page }, info) => {
  const auth = await isolate(page, info.project.use.colorScheme);
  const errors = [], failedAssets = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('response', response => {
    if (response.status() >= 400 && /\.(css|js)(\?|$)/.test(response.url())) failedAssets.push(response.url());
  });
  for (const path of paths) {
    auth.user = path === '/login' ? null : path === '/mfa-setup' ? { ...admin, mfa_enrolled: false } : admin;
    await open(page, path);
    expect(new URL(page.url()).pathname).toBe(path);
    const width = await page.evaluate(() => ({ body: document.body.scrollWidth, viewport: innerWidth }));
    expect(width.body, path).toBeLessThanOrEqual(width.viewport + 1);
    if (process.env.LAYOUT_CAPTURE === '1') {
      await page.screenshot({ path: info.outputPath(`${path.slice(1).replaceAll('/', '-')}.png`), animations: 'disabled' });
    }
  }
  expect(errors).toEqual([]);
  expect(failedAssets).toEqual([]);
});

test('desktop tables and mobile card wrappers are mutually exclusive', async ({ page }, info) => {
  await isolate(page, info.project.use.colorScheme);
  const mobile = page.viewportSize().width <= 768;
  for (const path of ['/dashboard', '/servers', '/gpu-analysis', '/reports', '/alerts', '/users', '/settings']) {
    await open(page, path);
    const wrappers = page.locator('.ant-spin-nested-loading.mobile-only');
    expect(await wrappers.count(), path).toBeGreaterThan(0);
    for (const wrapper of await wrappers.all()) {
      if (mobile) await expect(wrapper).toBeVisible();
      else await expect(wrapper).toBeHidden();
    }
    for (const table of await page.locator('.ant-table-wrapper.desktop-only').all()) {
      if (mobile) await expect(table).toBeHidden();
      else await expect(table).toBeVisible();
    }
  }
});

test('responsive metric grids preserve column counts and equal card heights', async ({ page }, info) => {
  await isolate(page, info.project.use.colorScheme);
  const width = page.viewportSize().width;
  for (const [path, selector, count] of [
    ['/dashboard', '.dashboard-kpis .ant-card', width >= 992 ? 4 : 2],
    ['/gpu-analysis', '.analysis-kpis .ant-card', width >= 992 ? 4 : 2],
    ['/reports', '.report-kpis .ant-card', width >= 768 ? 3 : 2],
    ['/servers/1', '.detail-kpis .ant-card', width >= 992 ? 4 : 2],
    ['/users', '.users-summary .ant-card', 3],
  ]) {
    await open(page, path);
    await sameRow(page, selector, count);
  }
});

test('settings actions align to their fields at every breakpoint', async ({ page }, info) => {
  await isolate(page, info.project.use.colorScheme);
  await open(page, '/settings');
  for (const selector of ['#settings-collection', '#settings-webhook', '#settings-thresholds', '.status-config-card']) {
    const positions = await page.locator(selector).evaluate(node => {
      const field = node.querySelector('.ant-input-number,.ant-input,.ant-input-affix-wrapper');
      const button = node.querySelector('.settings-form-actions .ant-btn,.status-config-actions .ant-btn');
      return { field: field.getBoundingClientRect().left, button: button.getBoundingClientRect().left };
    });
    expect(Math.abs(positions.field - positions.button), selector).toBeLessThan(1);
  }
  const columns = await page.locator('#settings-collection > .ant-card,#settings-webhook > .ant-card').evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().top));
  if (page.viewportSize().width >= 1200) expect(Math.abs(columns[0] - columns[1])).toBeLessThan(1);
  else expect(columns[1]).toBeGreaterThan(columns[0]);
});

test('long server links do not paint over adjacent table columns', async ({ page }, info) => {
  test.skip(page.viewportSize().width <= 768, 'Tables are hidden on mobile.');
  await isolate(page, info.project.use.colorScheme);
  for (const path of ['/servers', '/dashboard', '/reports', '/gpu-analysis']) {
    await open(page, path);
    const violations = await page.locator('.ant-table-cell .table-link,.ant-table-cell .server-link').evaluateAll(nodes => nodes.filter(node => {
      const link = node.getBoundingClientRect(), cell = node.closest('.ant-table-cell').getBoundingClientRect();
      return link.right > cell.right + 1 || getComputedStyle(node).overflowX !== 'hidden';
    }).map(node => node.textContent));
    expect(violations, path).toEqual([]);
  }
});

test('login status dot is aligned and the card fits the viewport', async ({ page }, info) => {
  const auth = await isolate(page, info.project.use.colorScheme);
  auth.user = null;
  await open(page, '/login');
  const alignment = await page.evaluate(() => {
    const dot = document.querySelector('.login-heading .ant-badge-status-dot').getBoundingClientRect();
    const title = document.querySelector('.login-heading h1').getBoundingClientRect();
    const card = document.querySelector('.login-card').getBoundingClientRect();
    return { delta: Math.abs(dot.top + dot.height / 2 - title.top - title.height / 2), left: card.left, right: card.right, top: card.top, bottom: card.bottom, viewport: innerWidth, height: innerHeight };
  });
  expect(alignment.delta).toBeLessThan(1);
  expect(alignment.left).toBeGreaterThanOrEqual(0);
  expect(alignment.right).toBeLessThanOrEqual(alignment.viewport);
  if (alignment.bottom - alignment.top < alignment.height) {
    expect(Math.abs(alignment.top + alignment.bottom - alignment.height)).toBeLessThan(2);
  }
});

test('native add dialogs fit the viewport and keep their footer accessible', async ({ page }, info) => {
  await isolate(page, info.project.use.colorScheme);
  for (const [path, name] of [['/servers', /添加服务器/], ['/users', /新建用户/]]) {
    await open(page, path);
    await page.getByRole('button', { name }).click();
    const dialog = page.locator('.ant-modal');
    await expect(dialog).toBeVisible();
    await page.waitForTimeout(350);
    const bounds = await dialog.evaluate(node => {
      const modal = node.getBoundingClientRect(), footer = node.querySelector('.ant-modal-footer').getBoundingClientRect();
      return { left: modal.left, right: modal.right, footerBottom: footer.bottom, width: innerWidth, height: innerHeight };
    });
    expect(bounds.left).toBeGreaterThanOrEqual(-1);
    expect(bounds.right).toBeLessThanOrEqual(bounds.width + 1);
    expect(bounds.footerBottom).toBeLessThanOrEqual(bounds.height + 1);
  }
});

test('cockpit shows only the unit picker relevant to the active chart', async ({ page }, info) => {
  await isolate(page, info.project.use.colorScheme);
  await open(page, '/cockpit');
  await expect(page.locator('.cockpit-page-actions .unit-pick-text')).toHaveCount(2);
  for (const picker of await page.locator('.cockpit-page-actions .unit-pick-text').all()) await expect(picker).toBeHidden();
  await page.getByText('网络', { exact: true }).first().click();
  await expect(page.locator('.cockpit-page-actions .unit-pick-text:visible')).toHaveCount(1);
});

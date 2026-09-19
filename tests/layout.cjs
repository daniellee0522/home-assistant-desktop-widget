const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

(async () => {
  const browser = await chromium.launch({headless: true, channel: 'msedge'});
  try {
    for (const scenario of [
      {role: 'settings'}, {role: 'grid'}, {role: 'flyout'},
      {role: 'settings', fixed: true, zoom: 200, dpr: 1.5},
      {role: 'grid', fixed: true, zoom: 150, dpr: 1.25},
      {role: 'flyout', fixed: true, zoom: 200, dpr: 2},
    ]) {
      const {role, fixed = false, zoom = 100, dpr = 1} = scenario;
      const page = await browser.newPage({viewport: {width: 340, height: 500}, deviceScaleFactor: dpr});
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      let sizes = [];
      await page.route('http://widget.test/**', async route => {
        const url = new URL(route.request().url());
        if (url.pathname.startsWith('/api/')) {
          const method = url.pathname.slice(5);
          const args = route.request().postDataJSON();
          let value = null;
          if (method === 'bootstrap') value = {config: {tiles: [], ha_token: '', columns: 4, zoom, theme: 'auto', fixed_size: fixed, fixed_width: 400, fixed_height: 300}, connected: false};
          if (method === 'fetch_initial_states') value = {};
          if (method.startsWith('resize_')) {
            sizes.push(args.slice(0, 2));
            if (sizes.length < 30) await page.setViewportSize({width: Math.ceil(args[0] / dpr), height: Math.ceil(args[1] / dpr)});
          }
          return route.fulfill({json: {value}});
        }
        const file = path.join(__dirname, '../web', url.pathname === '/' ? 'index.html' : url.pathname);
        await route.fulfill({body: fs.readFileSync(file), contentType: file.endsWith('.css') ? 'text/css' : file.endsWith('.js') ? 'text/javascript' : 'text/html'});
      });
      await page.goto('http://widget.test/#' + role);
      await page.waitForTimeout(1500);
      console.log(JSON.stringify(scenario), JSON.stringify(sizes), errors);
      assert.equal(errors.length, 0);
      assert(sizes.length < 10, 'layout must converge');
      if (role === 'settings') assert.equal(sizes.at(-1)[0], 340 * dpr, 'settings ignores widget fixed dimensions and zoom');
      if (role === 'settings') {
        const before = sizes.length;
        for (const theme of ['深色', '淺色', '深色']) {
          await page.locator('#theme-select-button').click();
          const menu = page.locator('#theme-select-menu');
          await menu.waitFor({state: 'visible'});
          const bounds = await menu.boundingBox();
          assert(bounds.x >= 0 && bounds.x + bounds.width <= page.viewportSize().width);
          assert(bounds.y >= 0 && bounds.y + bounds.height <= page.viewportSize().height);
          await menu.getByRole('option', {name: theme, exact: true}).click();
          await page.waitForFunction(value => document.documentElement.dataset.theme === value, theme === '深色' ? 'dark' : 'light');
        }
        await page.locator('#theme-select-button').focus();
        await page.keyboard.press('ArrowDown');
        await page.keyboard.press('Home');
        await page.keyboard.press('Enter');
        assert.equal(await page.locator('#theme-select').inputValue(), 'auto');
        await page.locator('#glass-mode-select-button').click();
        assert.equal(await page.locator('#glass-mode-select-menu [role="option"]').count(), 2);
        await page.keyboard.press('Escape');
        assert(await page.locator('#glass-mode-select-menu').count() === 0);
        assert(await page.locator('#view-settings').isVisible());
        await page.waitForTimeout(100);
        assert.equal(sizes.length, before, 'opening and choosing menu options must not resize the host');
      }
      if (role === 'grid' && fixed) assert.deepEqual(sizes.at(-1), [750, 563]);
      if (role === 'flyout') assert(await page.locator('#empty-hint').isHidden());
      await page.close();
    }
  } finally { await browser.close(); }
})().catch(e => {console.error(e); process.exitCode = 1;});

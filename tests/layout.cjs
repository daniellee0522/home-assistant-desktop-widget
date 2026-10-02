const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('fs');
const path = require('path');
const assert = require('assert');

(async () => {
  const browser = await chromium.launch({headless: true, channel: 'msedge'});
  try {
    // A widget is whole tile cells (152x146, 12 apart, 20 padding), so a
    // tile is the same size in every widget: [columns, rows] per size.
    const widgetPx = (cols, rows) => [cols * 152 + (cols - 1) * 14 + 28, rows * 146 + (rows - 1) * 14 + 28];
    const SIZES = {'1x1': [1, 1], '2x2': [2, 2], '2x4': [4, 2], '4x4': [4, 4]};
    for (const scenario of [
      {role: 'settings'}, {role: 'grid'}, {role: 'flyout'},
      {role: 'settings', zoom: 200, dpr: 1.5},
      {role: 'grid', size: '1x1', zoom: 150, dpr: 1.25, dprSwitch: true},
      {role: 'grid', size: '2x2'},
      {role: 'grid', size: '4x4', populated: true},
      {role: 'flyout', zoom: 200, dpr: 2},
      {role: 'flyout', populated: true, dpr: 1.5},
    ]) {
      const {role, size = '2x4', zoom = 100, dpr = 1, populated = false} = scenario;
      const tiles = populated ? [{id: 'test-light', entity: 'light.test', domain: 'light', room: 'Test room'}] : [];
      const page = await browser.newPage({viewport: {width: 340, height: 500}, deviceScaleFactor: dpr});
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      let sizes = [];
      let simulateHostResize = true;
      await page.route('http://widget.test/**', async route => {
        const url = new URL(route.request().url());
        if (url.pathname.startsWith('/api/')) {
          const method = url.pathname.slice(5);
          const args = route.request().postDataJSON();
          let value = null;
          if (method === 'bootstrap') value = {config: {widgets: [{id: 'w1', size, tiles}], panel: {mode: 'grid', tiles: null}, ha_token: '', zoom, theme: 'auto'}, connected: false};
          if (method === 'fetch_initial_states') value = {};
          if (method.startsWith('resize_')) {
            sizes.push(args.slice(0, 2));
            if (simulateHostResize && sizes.length < 30) await page.setViewportSize({width: Math.ceil(args[0] / dpr), height: Math.ceil(args[1] / dpr)});
          }
          return route.fulfill({json: {value}});
        }
        const file = path.join(__dirname, '../web', url.pathname === '/' ? 'index.html' : url.pathname);
        await route.fulfill({body: fs.readFileSync(file), contentType: file.endsWith('.css') ? 'text/css' : file.endsWith('.js') ? 'text/javascript' : 'text/html'});
      });
      await page.goto('http://widget.test/#' + (role === 'grid' ? 'grid:w1' : role));
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
      if (role === 'grid') {
        const [cols, rows] = SIZES[size];
        const want = widgetPx(cols, rows).map(side => side * zoom / 100 * dpr);
        assert(Math.abs(sizes.at(-1)[0] - want[0]) <= 1 && Math.abs(sizes.at(-1)[1] - want[1]) <= 1,
          `widget ${size} must be ${want}, got ${sizes.at(-1)}`);
      }
      if (role === 'flyout') assert(await page.locator('#empty-hint').isHidden());
      const beforeRecovery = sizes.length;
      const expectedSize = sizes.at(-1);
      await page.evaluate(() => window.__recoverDisplay());
      await page.waitForFunction(() => !backdropPending);
      await page.waitForTimeout(200);
      assert(sizes.length > beforeRecovery, 'resume must resend unchanged CSS dimensions');
      assert.deepEqual(sizes.at(-1), expectedSize, 'recovery must preserve layout and zoom');
      if (scenario.dprSwitch) {
        simulateHostResize = false;
        const client = await page.context().newCDPSession(page);
        await client.send('Emulation.setDeviceMetricsOverride', {
          ...page.viewportSize(), deviceScaleFactor: 2, mobile: false,
        });
        // Emulation changes DPR without reliably dispatching a media-query
        // event. Deliver the same recovery callback used by Qt's DPI hook.
        await page.evaluate(() => window.__recoverDisplay());
        await page.waitForTimeout(500);
        assert.deepEqual(sizes.at(-1), [540, 522], 'DPR-only change must resize physical viewport');
      }
      assert.equal(errors.length, 0);
      await page.close();
    }
  } finally { await browser.close(); }
})().catch(e => {console.error(e); process.exitCode = 1;});

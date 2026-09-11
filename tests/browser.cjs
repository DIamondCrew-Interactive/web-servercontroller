const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const root = path.resolve(__dirname, '../build/preview');
const mime = {'.html':'text/html; charset=utf-8','.css':'text/css','.js':'text/javascript','.png':'image/png','.woff2':'font/woff2'};
const server = http.createServer((req, res) => {
  const file = path.resolve(root, '.' + decodeURIComponent(req.url.split('?')[0]));
  if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
    res.writeHead(404); return res.end();
  }
  res.setHeader('Content-Type', mime[path.extname(file)] || 'application/octet-stream');
  fs.createReadStream(file).pipe(res);
});
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({channel: process.env.DCI_BROWSER || 'chrome', headless: true});
  let checks = 0;
  const screenshots = path.resolve(__dirname, '../build/screenshots');
  fs.mkdirSync(screenshots, {recursive: true});
  try {
    const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
    const errors = [];
    page.on('pageerror', err => errors.push(err.message));
    page.on('response', response => { if (response.status() >= 400) errors.push(`${response.status()} ${response.url()}`); });
    await page.goto(`${url}/login.html`);
    assert(await page.locator('#login-user-input').isVisible()); checks++;
    assert(await page.locator('#login-password-input').isVisible()); checks++;
    assert.equal(await page.locator('#brand').textContent(), 'DiamondCrew Interactive'); checks++;
    assert.equal(await page.locator('#brand').evaluate(el => getComputedStyle(el, '::after').content), '"Server Controller"'); checks++;
    await page.screenshot({path: path.join(screenshots, 'login-desktop.png'), fullPage: true});
    await page.locator('#login-button').click();
    assert(await page.locator('#error-group').isVisible()); checks++;
    await page.setViewportSize({width: 390, height: 844});
    await page.screenshot({path: path.join(screenshots, 'login-mobile.png'), fullPage: true});
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)); checks++;
    await page.setViewportSize({width: 1440, height: 1000});
    await page.goto(`${url}/index.html`);
    assert(await page.locator('.dci-brand').isVisible()); checks++;
    await page.frameLocator('iframe').locator('.pf-c-card').first().waitFor();
    assert.equal(await page.frameLocator('iframe').locator('.pf-c-card').first().evaluate(el => getComputedStyle(el).backgroundColor), 'rgb(10, 20, 36)'); checks++;
    await page.screenshot({path: path.join(screenshots, 'overview-desktop.png'), fullPage: true});
    for (const module of ['services','network','storage','updates','terminal','controls']) {
      await page.goto(`${url}/${module}.html`);
      assert.equal(await page.locator('body').evaluate(el => getComputedStyle(el).backgroundColor), 'rgb(5, 11, 23)'); checks++;
    }
    assert(await page.locator('#example-disabled').isDisabled()); checks++;
    await page.locator('#example-name').focus();
    assert.equal(await page.locator('#example-name').evaluate(el => getComputedStyle(el).outlineStyle), 'solid'); checks++;
    await page.locator('[data-open-dialog]').click();
    assert(await page.locator('dialog').isVisible()); checks++;
    await page.screenshot({path: path.join(screenshots, 'modal-desktop.png'), fullPage: true});
    await page.keyboard.press('Escape');
    assert(!(await page.locator('dialog').isVisible())); checks++;
    await page.setViewportSize({width: 390, height: 844});
    await page.goto(`${url}/overview.html`);
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)); checks++;
    await page.screenshot({path: path.join(screenshots, 'overview-mobile.png'), fullPage: true});
    assert.deepEqual(errors, []); checks++;
    fs.writeFileSync(path.resolve(__dirname, '../build/browser-results.json'), JSON.stringify({checks, browser: await browser.version(), errors, scope: 'Static fixtures, not Cockpit backend integration'}, null, 2));
    console.log(`${checks} browser assertions passed; screenshots in build/screenshots.`);
  } finally { await browser.close(); }
})().catch(err => { console.error(err); process.exitCode = 1; }).finally(() => server.close());

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
    await page.route('**/discord/status', route => route.fulfill({json: {enabled: true}}));
    await page.route('**/discord/redeem', route => route.fulfill({status: 204}));
    await page.goto(`${url}/login.html`);
    assert(await page.locator('#login-user-input').isVisible()); checks++;
    assert(await page.locator('#login-password-input').isVisible()); checks++;
    assert.equal(await page.locator('#brand').textContent(), 'DiamondCrew Interactive'); checks++;
    assert.equal(await page.locator('#brand').evaluate(el => getComputedStyle(el, '::after').content), '"Server Controller"'); checks++;
    await page.waitForFunction(() => document.querySelector('#dci-discord-login').getAttribute('aria-disabled') !== 'true');
    assert.equal(await page.locator('#dci-discord-login').textContent(), 'Pokračovat přes Discord'); checks++;
    assert.equal(await page.locator('.dci-login-motto').textContent(), 'Create. Play. Together.'); checks++;
    assert(await page.locator('#main #login-details').isVisible()); checks++;
    assert.equal(await page.locator('#login-details').evaluate(el => getComputedStyle(el).backgroundColor), 'rgba(0, 0, 0, 0)'); checks++;
    assert.equal(await page.locator('#login-password-toggle').evaluate(el => getComputedStyle(el).backgroundColor), 'rgb(12, 27, 44)'); checks++;
    assert.equal(await page.locator('label[for="login-user-input"]').evaluate(el => getComputedStyle(el).color), 'rgb(185, 203, 224)'); checks++;
    await page.screenshot({path: path.join(screenshots, 'login-desktop.png'), fullPage: true});
    await page.locator('#login-button').click();
    assert(await page.locator('#error-group').isVisible()); checks++;
    await page.setViewportSize({width: 390, height: 844});
    await page.screenshot({path: path.join(screenshots, 'login-mobile.png'), fullPage: true});
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)); checks++;
    await page.locator('#user-group').evaluate(el => { el.hidden = true; });
    await page.waitForFunction(() => document.querySelector('#dci-discord-options').hidden);
    assert(!(await page.locator('#dci-discord-login').isVisible())); checks++;
    await page.route('**/discord/status', route => route.fulfill({json: {enabled: false}}));
    await page.reload();
    await page.locator('#dci-discord-status').waitFor({state: 'visible'});
    assert.equal(await page.locator('#dci-discord-login').getAttribute('aria-disabled'), 'true'); checks++;
    assert(await page.locator('#login-password-input').isVisible()); checks++;
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
    const accounts = await browser.newPage();
    await accounts.route('**/*', route => route.fulfill({body: ''}));
    await accounts.setContent(fs.readFileSync(path.resolve(__dirname, '../discord/ui/index.html'), 'utf8').replace(/<script\b[^>]*>.*?<\/script>/gs, ''));
    await accounts.evaluate(() => {
      window.commands = []; window.bindings = {};
      window.cockpit = {spawn: async (args, options) => {
        window.commands.push({args, options});
        const operation = args[3];
        if (operation === 'link') window.bindings[args[7]] = {username: args[5], uid: 1000};
        if (operation === 'unlink') window.bindings = {};
        return JSON.stringify({users: ['demo'], links: window.bindings});
      }};
    });
    await accounts.addScriptTag({content: fs.readFileSync(path.resolve(__dirname, '../discord/ui/accounts.js'), 'utf8')});
    await accounts.locator('#load').click();
    await accounts.locator('#editor').waitFor({state: 'visible'});
    assert.equal(await accounts.locator('#user').inputValue(), 'demo'); checks++;
    await accounts.locator('#discord-id').fill('123456789012345678');
    await accounts.locator('button[type=submit]').click();
    await accounts.locator('#links button').waitFor();
    assert.equal(await accounts.locator('#links td').nth(1).textContent(), '123456789012345678'); checks++;
    await accounts.locator('#links button').click();
    await accounts.waitForFunction(() => !document.querySelector('#links tr'));
    assert(await accounts.evaluate(() => commands.every(command => command.options.superuser === 'require'))); checks++;
    await accounts.close();
    assert.deepEqual(errors, []); checks++;
    fs.writeFileSync(path.resolve(__dirname, '../build/browser-results.json'), JSON.stringify({checks, browser: await browser.version(), errors, scope: 'Static fixtures, not Cockpit backend integration'}, null, 2));
    console.log(`${checks} browser assertions passed; screenshots in build/screenshots.`);
  } finally { await browser.close(); }
})().catch(err => { console.error(err); process.exitCode = 1; }).finally(() => server.close());

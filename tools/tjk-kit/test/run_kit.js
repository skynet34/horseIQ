const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
// Usage: node tools/tjk-kit/test/run_kit.js tools/tjk-kit/install.html   (needs: npm i playwright)
const DIR = __dirname.replace(/\\/g, '/');
(async () => {
  const html = fs.readFileSync(process.argv[2], 'utf8');
  const m = html.match(/href="(javascript:[^"]+)"/);
  const code = decodeURIComponent(m[1].replace(/&amp;/g,'&').replace(/&quot;/g,'"').slice('javascript:'.length));
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ acceptDownloads: true });
  const page = await ctx.newPage();
  page.on('pageerror', e => console.log('PAGEERROR', e.message));
  // horse page (URL with AtId via query string on file://)
  await page.goto('file://' + (DIR.startsWith('/') ? '' : '/') + DIR + '/AtKosuBilgileri.html?1=1&QueryParameter_AtId=112812');
  const [dl] = await Promise.all([page.waitForEvent('download'), page.evaluate(code)]);
  const out = path.join(DIR, dl.suggestedFilename());
  await dl.saveAs(out);
  console.log('DOWNLOAD', out);
  console.log('TOAST', await page.evaluate(() => document.body.lastElementChild.textContent));
  // results page
  await page.goto('file://' + (DIR.startsWith('/') ? '' : '/') + DIR + '/GunlukYarisSonuclari.html');
  await page.evaluate(code);
  console.log('LIST', (await page.locator('#horseiq-kit').innerText()).replace(/\n/g,' / '));
  await page.setViewportSize({width: 1000, height: 500});
  await page.screenshot({ path: path.join(DIR, 'list.png') });
  await browser.close();
})();

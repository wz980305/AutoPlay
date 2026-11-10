// Screenshots of the CarPlay page (dist/) and the box page at the Tesla browser's window shapes (1.2.0,
// docs/UI-1.2.0.md; 1.3.0, docs/UI-1.3.0.md; 1.5.0, docs/UI-1.5.0.md). Everything is served and mocked locally: no box,
// iPhone or car is needed.
//
//   npm run build:offline                                   # dist/
//   python3 ../../box/tools/render_settings_states.py out/box-states
//   node scripts/ui-shots.mjs out/ui-shots [viewer|box|twins]   # needs playwright-core and a Chromium (CHROME=<path>)
//
// Shapes (docs/TESLA.md): the windowed browser is about 773x601 CSS px and the borderless page 1256x706, both at a
// device scale of about 1.53; a 560 px tall case stands in for a keyboard or a taller bottom bar; 1920x1200 at 1.0 is
// the reference; the phone case is for the box page only (a pairing is also confirmed from a phone).
// The viewer's box link, display API and WebSocket are mocked; its H.264 support probe is forced to "supported" so a
// headless Chromium without a hardware decoder shows the page and not the browser check.
import { mkdirSync } from 'node:fs';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = fileURLToPath(new URL('.', import.meta.url));
const OUT = resolve(process.argv[2] ?? 'out/ui-shots'); mkdirSync(OUT, { recursive: true });
const ONLY = process.argv[3] ?? '';
const want = part => !ONLY || ONLY === part;
const DIST = resolve(here, '../dist');
const BOX_STATES = resolve(process.env.BOX_STATES ?? 'out/box-states');
const TOKEN = '0123456789abcdef0123456789abcdef';
const SHAPES = [
  { w: 773, h: 601, dsf: 1.53, tag: 'tesla-window' },
  { w: 1256, h: 706, dsf: 1.53, tag: 'tesla-borderless' },
  { w: 1256, h: 560, dsf: 1.53, tag: 'tesla-short' },
  { w: 1920, h: 1200, dsf: 1, tag: 'ref-1920' },
  { w: 390, h: 844, dsf: 3, tag: 'phone' },
];
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.svg': 'image/svg+xml' };

let chromium;
try { ({ chromium } = await import('playwright-core')); }
catch { ({ chromium } = await import('playwright')); }

function serve(dir) {
  const server = createServer(async (req, res) => {
    const path = decodeURIComponent(new URL(req.url, 'http://x').pathname);
    const file = join(dir, path === '/' ? 'index.html' : path);
    try { const body = await readFile(file); res.writeHead(200, { 'Content-Type': TYPES[extname(file)] ?? 'application/octet-stream' }); res.end(body); }
    catch { res.writeHead(404); res.end('not found'); }
  });
  return new Promise(ok => server.listen(0, '127.0.0.1', () => ok({ server, url: `http://127.0.0.1:${server.address().port}/` })));
}

const dist = await serve(DIST);
const box = await serve(BOX_STATES);
const browser = await chromium.launch({ executablePath: process.env.CHROME, args: ['--no-sandbox'] });
const shot = async (page, name, vp) => { const file = `${OUT}/${vp.tag}-${name}.png`; await page.screenshot({ path: file }); console.log('  saved', file); };

async function viewer(vp, opts = {}) {
  const ctx = await browser.newContext({ viewport: { width: vp.w, height: vp.h }, deviceScaleFactor: vp.dsf, locale: 'zh-CN', colorScheme: 'dark' });
  await ctx.addInitScript(() => { if (typeof VideoDecoder !== 'undefined') VideoDecoder.isConfigSupported = () => Promise.resolve({ supported: true }); });
  if (opts.lang) await ctx.addInitScript(lang => { try { localStorage.setItem('f50-language', lang); } catch { /* no storage */ } }, opts.lang);
  // The night mode decides the panel's colours since 1.5.0; left at "schedule" a run would depend on the time of day.
  await ctx.addInitScript(mode => { try { if (!localStorage.getItem('f50-night-mode')) localStorage.setItem('f50-night-mode', mode); } catch { /* no storage */ } }, opts.night ?? 'night');
  await ctx.route('**/receiver-access.json', r => r.fulfill({ json: { token: TOKEN, settingsPort: 18080 } }));
  await ctx.route('**/api/display*', r => r.request().method() === 'POST' ? r.fulfill({ json: { ok: true } })
    : r.fulfill({ json: { width: 1920, height: 1080, fps: 30, uiScale: 85, hevc: false } }));
  const page = await ctx.newPage();
  page.on('pageerror', e => console.log('  pageerror:', e.message));
  const sockets = []; const link = { down: false };
  await page.routeWebSocket(/\/ws/, ws => {
    if (link.down) { ws.close({ code: 1006, reason: 'box away' }); return; }
    sockets.push(ws); ws.send(JSON.stringify({ type: 'hello', sessionActive: false, deviceName: 'iPhone' }));
  });
  await page.goto(`${dist.url}index.html`); await page.waitForTimeout(600);
  return { ctx, page, sockets, link };
}
/** A painted picture without a decoder: a drawn canvas and the live state on #app. */
async function goLive(page) {
  await page.evaluate(() => {
    const canvas = document.getElementById('screen'); canvas.width = 1920; canvas.height = 1080;
    const c = canvas.getContext('2d'); const g = c.createLinearGradient(0, 0, 1920, 1080); g.addColorStop(0, '#1b2a34'); g.addColorStop(1, '#0e151a');
    c.fillStyle = g; c.fillRect(0, 0, 1920, 1080); c.fillStyle = 'rgba(0,0,0,.55)'; c.fillRect(0, 0, 150, 1080);
    for (let i = 0; i < 8; i++) { c.fillStyle = `hsl(${i * 45},60%,50%)`; c.beginPath(); c.roundRect(260 + (i % 4) * 180, 200 + Math.floor(i / 4) * 180, 140, 140, 30); c.fill(); }
    const app = document.getElementById('app'); app.dataset.state = 'live'; app.dataset.live = '1';
    document.getElementById('overlay').hidden = true;
  });
  await page.waitForTimeout(300);
}
const settle = page => page.waitForTimeout(350);

if (want('viewer')) for (const vp of SHAPES) {
  if (vp.tag === 'phone') continue;
  console.log(`viewer ${vp.tag} ${vp.w}x${vp.h}@${vp.dsf}`);
  const { ctx, page, sockets, link } = await viewer(vp);
  await shot(page, 'viewer-waiting', vp);
  await goLive(page); await shot(page, 'viewer-live', vp);
  await page.evaluate(() => document.getElementById('btn-settings').click()); await page.waitForTimeout(500);
  await shot(page, 'viewer-settings-general', vp);
  const measured = await page.evaluate(() => ({ docW: document.documentElement.scrollWidth, winW: innerWidth,
    label: getComputedStyle(document.querySelector('.settings-page .cell .main b')).fontSize, value: getComputedStyle(document.querySelector('.settings-page .select-row .value')).fontSize,
    cell: Math.round(document.querySelector('.settings-page .select-row').getBoundingClientRect().height) }));
  await page.click('[data-picker="night-mode"]'); await settle(page); await shot(page, 'viewer-picker-night', vp);
  // "Follow the browser" (dark here), so the rest of the pass stays in the night colours.
  await page.click('#picker-options .option:nth-child(2)'); await settle(page); await shot(page, 'viewer-settings-general-picked', vp);
  await page.click('[data-settings-page="display"]'); await settle(page); await shot(page, 'viewer-settings-display', vp);
  await page.click('[data-picker="ui-scale"]'); await settle(page); await shot(page, 'viewer-picker-ui', vp);
  await page.keyboard.press('Escape'); await settle(page);
  await page.click('#settings-display details > summary'); await page.waitForTimeout(700); await shot(page, 'viewer-settings-display-advanced', vp);
  await page.click('[data-picker="codec"]'); await settle(page); await shot(page, 'viewer-picker-codec', vp);
  await page.click('#picker-cancel'); await settle(page);
  await page.click('[data-settings-page="connection"]'); await settle(page); await shot(page, 'viewer-settings-connection', vp);
  await page.locator('#settings-connection details > summary').first().click(); await page.waitForTimeout(700); await shot(page, 'viewer-settings-connection-diagnostics', vp);
  await page.click('#btn-close'); await page.waitForTimeout(400);
  link.down = true; for (const ws of sockets) await ws.close({ code: 1006, reason: 'test' }).catch(() => {});
  await page.waitForTimeout(2500); await shot(page, 'viewer-reconnecting', vp);
  console.log('   ', JSON.stringify({ ...measured, state: await page.evaluate(() => document.getElementById('app').dataset.state) }));
  await ctx.close();
}
// Day (1.5.0): the waiting screen, the panel and its sheets in the light colours, at the two shapes the car shows.
// Picking 夜间 in the sheet turns the page dark at once.
if (want('viewer')) for (const vp of SHAPES.slice(0, 2)) {
  console.log(`viewer day ${vp.tag}`);
  const { ctx, page } = await viewer(vp, { night: 'day' });
  await shot(page, 'viewer-waiting-day', vp);
  await goLive(page);
  await page.evaluate(() => document.getElementById('btn-settings').click()); await page.waitForTimeout(500);
  await shot(page, 'viewer-settings-general-day', vp);
  const seen = await page.evaluate(() => ({ theme: document.documentElement.dataset.theme, panel: getComputedStyle(document.getElementById('settings')).backgroundColor,
    cell: getComputedStyle(document.querySelector('#settings .group')).backgroundColor, label: getComputedStyle(document.querySelector('#settings .cell .main b')).color,
    waiting: getComputedStyle(document.getElementById('overlay')).backgroundColor, link: document.getElementById('box-link-panel').href, docW: document.documentElement.scrollWidth, winW: innerWidth }));
  console.log('   ', JSON.stringify(seen));
  await page.click('[data-picker="night-mode"]'); await settle(page); await shot(page, 'viewer-picker-night-day', vp);
  await page.keyboard.press('Escape'); await settle(page);
  await page.click('[data-settings-page="display"]'); await settle(page); await shot(page, 'viewer-settings-display-day', vp);
  await page.click('#settings-display details > summary'); await page.waitForTimeout(700); await shot(page, 'viewer-settings-display-advanced-day', vp);
  await page.click('[data-settings-page="connection"]'); await settle(page);
  await page.locator('#settings-connection details > summary').first().click(); await page.waitForTimeout(700); await shot(page, 'viewer-settings-connection-day', vp);
  await page.click('[data-settings-page="general"]'); await settle(page);
  // A notice inside the panel: the location switch without the browser's permission (headless refuses it).
  await page.click('#car-location-on'); await page.waitForTimeout(900); await shot(page, 'viewer-settings-general-day-notice', vp);
  await page.waitForTimeout(6500);
  await page.click('[data-picker="night-mode"]'); await settle(page);
  await page.click('#picker-options .option:nth-child(4)'); await settle(page); await shot(page, 'viewer-settings-general-day-to-night', vp);
  console.log('   ', JSON.stringify(await page.evaluate(() => ({ theme: document.documentElement.dataset.theme, panel: getComputedStyle(document.getElementById('settings')).backgroundColor,
    link: document.getElementById('box-link-panel').href }))));
  await ctx.close();
}
if (want('viewer')) {   // English labels (the longest strings) at the windowed shape
  const vp = SHAPES[0];
  const { ctx, page } = await viewer(vp, { lang: 'en' });
  await shot(page, 'viewer-waiting-en', vp);
  await page.evaluate(() => document.getElementById('btn-settings').click()); await page.waitForTimeout(500); await shot(page, 'viewer-settings-general-en', vp);
  await page.click('[data-picker="night-mode"]'); await settle(page); await shot(page, 'viewer-picker-night-en', vp);
  await page.keyboard.press('Escape'); await settle(page);
  await page.click('[data-settings-page="display"]'); await settle(page); await shot(page, 'viewer-settings-display-en', vp);
  await page.click('#settings-display details > summary'); await page.waitForTimeout(700); await shot(page, 'viewer-settings-display-advanced-en', vp);
  await ctx.close();
}
// The box page (1.5.0: the panel's twin). A name is a state of render_settings_states.py, with #net, #update or #more
// for a category other than the first. Each is opened as the CarPlay page's settings panel links to it, with
// ?night=1 or 0 and from=panel (the bar's button then reads 返回), in a browser whose own preference is the opposite: a
// picture in the wrong colours shows at once.
const BOX = ['fresh', 'live', 'live#net', 'live#more', 'available#update', 'checking#update', 'invited#update', 'live-open', 'invited', 'hot',
  'bt-failed', 'pair-waiting', 'pair-confirm', 'ask-remove', 'ask-install', 'reset'];
if (want('box')) for (const vp of SHAPES) {
  console.log(`box ${vp.tag} ${vp.w}x${vp.h}@${vp.dsf}`);
  for (const name of BOX) {
    const [state, pane] = name.split('#');
    for (const night of (vp.tag === 'tesla-window' || vp.tag === 'phone' ? [1, 0] : [1])) {
      const ctx = await browser.newContext({ viewport: { width: vp.w, height: vp.h }, deviceScaleFactor: vp.dsf, locale: 'zh-CN', colorScheme: night ? 'light' : 'dark' });
      const page = await ctx.newPage();
      page.on('pageerror', e => console.log('  pageerror:', e.message));
      await page.goto(`${box.url}box-${state}.html?night=${night}&from=panel${pane ? `#${pane}` : ''}`); await page.waitForTimeout(300);
      await shot(page, `box-${name.replace('#', '-')}-${night ? 'night' : 'day'}`, vp);
      const seen = await page.evaluate(() => {
        const px = sel => { const e = document.querySelector(sel); return e ? Math.round(parseFloat(getComputedStyle(e).fontSize) * 10) / 10 : null; };
        const rect = sel => { const e = document.querySelector(sel); if (!e) return null; const r = e.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; };
        return { h1: px('h1'), label: px('.pane.first .cell .main b'), cell: rect('.pane.first .cell'), nav: rect('.nav a'), theme: document.documentElement.dataset.theme, bg: getComputedStyle(document.body).backgroundColor,
          docW: document.documentElement.scrollWidth, winW: innerWidth, y: scrollY, query: location.search };
      });
      if (seen.docW > seen.winW || seen.theme !== (night ? 'dark' : 'light') || seen.query || (seen.y && state !== 'live-open')) console.log('  WRONG', name, JSON.stringify(seen));
      if (name === 'live' && night) console.log('   ', JSON.stringify(seen));
      await ctx.close();
    }
  }
}
// Twins (1.5.1): the panel's title bar, categories and first heading sit where the box page's do. The two style sheets
// live apart, so this is measured, shape by shape - the car's windows, a phone, a narrow window and one wider than the
// 1440 px the columns keep to. More than half a pixel apart is said and fails the run. (Playwright hides scrollbars. A
// browser with standing ones puts the box page's at the window's edge, beside the bar, and the panel's beside its page.)
const PLACES = selectors => Object.fromEntries(Object.entries(selectors).map(([name, selector]) => {
  const r = document.querySelector(selector).getBoundingClientRect();
  return [name, { x: r.left, y: r.top, r: innerWidth - r.right, h: r.height }];
}));
const COMPARED = { bar: 'yh', title: 'xyh', button: 'ryh', category: 'xyh', heading: 'xy', row: 'xrh' };
if (want('twins')) for (const vp of [...SHAPES, { w: 600, h: 800, dsf: 2, tag: 'narrow' }, { w: 1710, h: 960, dsf: 1, tag: 'wide' }]) {
  const { ctx, page } = await viewer(vp);
  await page.evaluate(() => document.getElementById('btn-settings').click()); await page.waitForTimeout(500);
  await page.click('[data-settings-page="connection"]'); await settle(page);
  const panel = await page.evaluate(PLACES, { bar: 'dialog[open] header', title: 'dialog[open] header h2', button: '#btn-close', category: '.settings-nav button',
    heading: '.settings-page:not([hidden]) .group-title', row: '.settings-page:not([hidden]) .group .cell' });
  await ctx.close();
  const ctx2 = await browser.newContext({ viewport: { width: vp.w, height: vp.h }, deviceScaleFactor: vp.dsf, locale: 'zh-CN', colorScheme: 'dark' });
  const page2 = await ctx2.newPage();
  await page2.goto(`${box.url}box-live.html?night=1&from=panel#net`); await page2.waitForTimeout(300);
  const twin = await page2.evaluate(PLACES, { bar: 'header', title: 'header h1', button: 'a.done', category: '.nav a', heading: '.pane:target .group-title', row: '.pane:target .group .cell' });
  await ctx2.close();
  const apart = Object.entries(COMPARED).flatMap(([name, keys]) => [...keys].filter(k => Math.abs(panel[name][k] - twin[name][k]) > 0.5)
    .map(k => `${name}.${k} ${Math.round(panel[name][k] * 10) / 10} / ${Math.round(twin[name][k] * 10) / 10}`));
  console.log(`twins ${vp.tag} ${vp.w}x${vp.h}: ${apart.length ? 'APART (panel / box page) ' + apart.join('; ') : `same (bar ${Math.round(panel.bar.h)} px, title at ${Math.round(panel.title.x)}, button ${Math.round(panel.button.r)} from the right)`}`);
  if (apart.length) process.exitCode = 1;
}
await browser.close(); dist.server.close(); box.server.close();

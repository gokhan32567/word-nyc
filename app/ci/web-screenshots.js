// App Store screenshots of the app's screens, rendered in headless Chromium (Linux runner, software WebGL).
// Fallback for app/ci/screenshots.py: the macOS simulator on CI has no GPU, so the WebGL map crawls there.
// The pages are the live site exactly as the app shows them: the app's user agent (no ads, app-only UI),
// a stand-in for the native bridge, the iPhone's safe areas and a status bar drawn on top.
// 6.9-inch iPhone: 440 x 956 points at 3x = 1320 x 2868.
//
//   node app/ci/web-screenshots.js app/store/screenshots
const { chromium, devices } = require('playwright');
const fs = require('fs');
const path = require('path');

const SITE = 'https://word-nyc.com';
const out = process.argv[2] || 'app/store/screenshots';
const events = JSON.parse(fs.readFileSync(path.join(__dirname, '../../events.json'), 'utf8')).events;

// same keys as index.html (venue slug + start in minutes into the night)
const slug = (s) => (String(s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').replace(/[^\x00-\x7f]/g, '')
  .toLowerCase().replace(/&/g, ' and ').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'venue');
const mins = (t) => {
  const m = String(t || '').trim().toUpperCase().match(/^(\d{1,2})(?::(\d{2}))?\s*(AM|PM)$/);
  if (!m) return null;
  const v = ((+m[1] % 12) + (m[3] === 'PM' ? 12 : 0)) * 60 + (+m[2] || 0);
  return v < 300 ? v + 1440 : v;
};
const evening = events.filter((e) => { const m = mins(e.time); return m >= 19 * 60 && m <= 22 * 60; });
const pick = evening.find((e) => e.image && e.description) || evening[0];
const showKey = pick ? `${slug(pick.venue)}-${mins(pick.time)}` : null;
const counts = {};
events.forEach((e) => { counts[e.venue] = (counts[e.venue] || 0) + 1; });
const venue = ['Village Vanguard', 'Blue Note Jazz Club', 'Smalls Jazz Club', 'Birdland'].find((v) => counts[v]) ||
  Object.keys(counts).sort((a, b) => counts[b] - counts[a])[0];

const shots = [
  ['1-map', '/?now=9:15pm'],
  ['2-list', '/?now=9:15pm&drawer=full'],
  showKey && ['3-show', `/?now=7:15pm&show=${showKey}`],
  ['4-jazz', '/?now=10:30pm&genre=Jazz'],
  venue && ['5-venue', `/venues/${slug(venue)}/`],
].filter(Boolean);

const STATUS_BAR = `
  <div style="position:fixed;inset:0 0 auto 0;height:62px;z-index:2147483647;pointer-events:none;
              font:600 17px/1 -apple-system,'SF Pro Text','Inter','Helvetica Neue',Arial,sans-serif;color:#fff">
    <span style="position:absolute;left:52px;top:22px;letter-spacing:-.2px">9:41</span>
    <span style="position:absolute;left:50%;top:11px;width:125px;height:37px;margin-left:-62.5px;border-radius:20px;background:#000"></span>
    <svg style="position:absolute;right:98px;top:23px" width="19" height="12" viewBox="0 0 19 12" fill="#fff">
      <rect x="0" y="8" width="3.2" height="4" rx="1"/><rect x="5" y="5.5" width="3.2" height="6.5" rx="1"/>
      <rect x="10" y="3" width="3.2" height="9" rx="1"/><rect x="15" y="0" width="3.2" height="12" rx="1"/></svg>
    <svg style="position:absolute;right:72px;top:22.5px" width="17" height="12.5" viewBox="0 0 17 12.5" fill="#fff">
      <path d="M8.5 2.6c2.4 0 4.6.9 6.3 2.5l1.3-1.3A10.6 10.6 0 0 0 8.5.8 10.6 10.6 0 0 0 .9 3.8l1.3 1.3a8.8 8.8 0 0 1 6.3-2.5Z"/>
      <path d="M8.5 6.2c1.4 0 2.7.5 3.7 1.4l1.3-1.3a7.2 7.2 0 0 0-10 0l1.3 1.3c1-.9 2.3-1.4 3.7-1.4Z"/>
      <path d="M8.5 9.6c.5 0 .9.2 1.2.5l-1.2 1.9-1.2-1.9c.3-.3.7-.5 1.2-.5Z"/></svg>
    <svg style="position:absolute;right:38px;top:22px" width="27" height="13" viewBox="0 0 27 13">
      <rect x=".5" y=".5" width="23" height="12" rx="3.8" fill="none" stroke="#fff" stroke-opacity=".4"/>
      <rect x="2" y="2" width="20" height="9" rx="2.5" fill="#fff"/><path d="M25 4.5v4c.8-.3 1.3-1.1 1.3-2s-.5-1.7-1.3-2Z" fill="#fff" fill-opacity=".4"/></svg>
  </div>`;

// what env(safe-area-inset-*) gives inside the app on this iPhone
const SAFE_AREA_CSS = `
  .topbar { padding-top: 62px !important; }
  .wrap { padding-top: 72px !important; }
  .drawer-body { padding-bottom: 50px !important; }
  .d-body { padding-bottom: 58px !important; }`;

(async () => {
  fs.mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--ignore-gpu-blocklist'] });
  const ctx = await browser.newContext({
    ...devices['iPhone 15 Pro Max'],
    viewport: { width: 440, height: 956 }, screen: { width: 440, height: 956 }, deviceScaleFactor: 3,
    userAgent: devices['iPhone 15 Pro Max'].userAgent + ' WordNYCApp/1.0',
    colorScheme: 'dark', timezoneId: 'America/New_York', locale: 'en-US',
  });
  await ctx.addInitScript((css) => {
    // stand-in for the app's native bridge (notifications off, nothing saved yet)
    window.Capacitor = {
      nativePromise: (p, m) => Promise.resolve(m === 'pushState' ? { permission: 'default', optedIn: false } : {}),
      addListener() {},
    };
    // the iPhone's safe areas, in place before the page lays out
    const style = document.createElement('style');
    style.textContent = css;
    const add = () => { if (!document.documentElement) return false; document.documentElement.appendChild(style); return true; };
    if (!add()) new MutationObserver((_, o) => { if (add()) o.disconnect(); }).observe(document, { childList: true });
  }, SAFE_AREA_CSS);
  const page = await ctx.newPage();
  for (const [name, p] of shots) {
    await page.goto(SITE + p, { waitUntil: 'networkidle', timeout: 90000 }).catch(() => {});
    await page.evaluate((html) => document.body.insertAdjacentHTML('beforeend', html), STATUS_BAR);
    await page.waitForTimeout(name === '3-show' ? 6000 : 5000); // map tiles, fly-to, fonts
    await page.screenshot({ path: path.join(out, `${name}.png`) });
    console.log('saved', name, p);
  }
  await browser.close();
})();

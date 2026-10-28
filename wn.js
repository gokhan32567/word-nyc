/* Word NYC shared helpers, loaded by every page.
   - WN.inApp: true inside the iPhone app (its web view adds "WordNYCApp/<version>" to the user agent)
   - WN.native(): calls the app's native code (push, share, in-app browser, offline copy)
   - WN.favs: favorite venues, kept on this device only (no account), mirrored to OneSignal tags so the
     noon push can mention them
   - WN.track(): cookie-free counts for sponsor reports. No IDs, no cookies, no IP stored: each event is
     just { metric, platform, key } and is added to a daily total by the stats worker (stats/worker.js).
*/
(function () {
  'use strict';
  // Filled in by .github/workflows/stats-worker.yml once the Cloudflare worker is deployed. Empty = counts off.
  var STATS_URL = '';
  var TAG_LIMIT = 5; // OneSignal's free plan allows 6 tags per user; favorites use at most 5

  var inApp = /WordNYCApp\//.test(navigator.userAgent);
  // Robots and previews (?now=... is used for screenshots) aren't counted.
  var bot = navigator.webdriver === true || /bot|crawl|spider|lighthouse|headless/i.test(navigator.userAgent) ||
    /[?&]now=/.test(location.search);

  function ls(key, value) {
    try {
      if (value === undefined) return localStorage.getItem(key);
      if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, value);
    } catch (_) { return null; }
    return null;
  }
  function lsJSON(key, fallback) {
    try { var v = JSON.parse(ls(key) || 'null'); return v == null ? fallback : v; } catch (_) { return fallback; }
  }

  /* ---------- native bridge (Capacitor injects window.Capacitor into the app's web view) ---------- */
  function hasNative() {
    var C = window.Capacitor;
    return inApp && !!(C && C.nativePromise);
  }
  function native(method, args) {
    if (!hasNative()) return Promise.reject(new Error('Not in the app'));
    return window.Capacitor.nativePromise('WordNYC', method, args || {});
  }
  function onNative(event, cb) {
    if (hasNative() && window.Capacitor.addListener) window.Capacitor.addListener('WordNYC', event, cb);
  }

  /* ---------- counts ---------- */
  // New York calendar day, used for "first open today" (unique daily users without any ID)
  function nyDay() {
    try {
      return new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
    } catch (_) { return new Date().toISOString().slice(0, 10); }
  }
  function track(metric, key, extra) {
    if (!STATS_URL || bot) return;
    var payload = { m: metric, p: inApp ? 'app' : 'web', k: String(key || '').slice(0, 80) };
    if (extra) for (var x in extra) payload[x] = extra[x];
    var body = JSON.stringify(payload), url = STATS_URL + '/e';
    try { if (navigator.sendBeacon && navigator.sendBeacon(url, body)) return; } catch (_) {}
    try { fetch(url, { method: 'POST', body: body, keepalive: true, mode: 'no-cors' }); } catch (_) {}
  }
  // One "open" per launch (and per return after 30+ minutes away). f=1 marks the first open of the day.
  function countOpen(via) {
    var day = nyDay(), first = 0;
    if (ls('wn.day') !== day) { ls('wn.day', day); first = ls('wn.day') === day ? 1 : 0; }
    track('open', via || '', { f: first });
  }

  /* ---------- links shared from the app or the site ---------- */
  function shareUrl(url) {
    try {
      var u = new URL(url, location.origin);
      u.searchParams.set('utm_source', inApp ? 'app_share' : 'share');
      u.searchParams.set('utm_medium', 'social');
      return u.toString();
    } catch (_) { return url; }
  }

  /* ---------- favorite venues ---------- */
  // Stored as [{ s: slug, n: name, t: time added }], newest last.
  var FAV_KEY = 'wn.favs', TAGGED_KEY = 'wn.favTags';
  function favList() {
    var v = lsJSON(FAV_KEY, []);
    return Array.isArray(v) ? v.filter(function (f) { return f && typeof f.s === 'string'; }) : [];
  }
  function isFav(slug) { return favList().some(function (f) { return f.s === slug; }); }
  function saveFavs(list) {
    ls(FAV_KEY, JSON.stringify(list));
    if (hasNative()) native('setFavorites', { json: JSON.stringify(list) }).catch(function () {});
    syncTags();
    try { window.dispatchEvent(new CustomEvent('wn:favs', { detail: list })); } catch (_) {}
  }
  function toggleFav(slug, name) {
    var list = favList(), on = !list.some(function (f) { return f.s === slug; });
    list = list.filter(function (f) { return f.s !== slug; });
    if (on) list.push({ s: slug, n: String(name || slug).slice(0, 80), t: Date.now() });
    saveFavs(list);
    track(on ? 'fav' : 'unfav', slug);
    return on;
  }
  // OneSignal tags: fav_<slug> = "1" for the newest TAG_LIMIT favorites. Only the difference is sent.
  function syncTags() {
    var want = favList().slice(-TAG_LIMIT).map(function (f) { return 'fav_' + f.s; });
    var had = lsJSON(TAGGED_KEY, []);
    var add = {}, remove = [], nAdd = 0;
    want.forEach(function (k) { if (had.indexOf(k) < 0) { add[k] = '1'; nAdd++; } });
    had.forEach(function (k) { if (want.indexOf(k) < 0) remove.push(k); });
    if (!nAdd && !remove.length) return;
    var done = function () { ls(TAGGED_KEY, JSON.stringify(want)); };
    if (hasNative()) {
      native('setTags', { add: add, remove: remove }).then(done).catch(function () {});
    } else if (window.OneSignalDeferred) {
      window.OneSignalDeferred.push(function (OneSignal) {
        try {
          if (remove.length) OneSignal.User.removeTags(remove);
          if (nAdd) OneSignal.User.addTags(add);
          done();
        } catch (_) {}
      });
    } // pages without OneSignal leave the difference for the next visit to the map
  }
  // The app keeps a native copy, in case the web view's storage is ever cleared.
  function restoreFavs() {
    if (!hasNative() || favList().length) return Promise.resolve();
    return native('getFavorites').then(function (r) {
      var list = [];
      try { list = JSON.parse((r && r.json) || '[]'); } catch (_) {}
      if (Array.isArray(list) && list.length) { ls(FAV_KEY, JSON.stringify(list)); ls(TAGGED_KEY, null); syncTags(); }
    }).catch(function () {});
  }

  // Heart buttons on static pages: <button class="fav-btn" data-fav-venue="slug" data-fav-name="Name" hidden>
  function heartLabel(btn, on) {
    var name = btn.getAttribute('data-fav-name') || 'this venue';
    btn.setAttribute('aria-pressed', String(on));
    btn.setAttribute('aria-label', on ? 'Unfollow ' + name : 'Follow ' + name);
    btn.innerHTML = (on ? '&#9829;' : '&#9825;') + '<span>' + (on ? 'Following' : 'Follow') + '</span>';
  }
  function mountHearts(root) {
    var btns = (root || document).querySelectorAll('[data-fav-venue]');
    Array.prototype.forEach.call(btns, function (btn) {
      if (btn.__wn) return;
      btn.__wn = true;
      var slug = btn.getAttribute('data-fav-venue');
      heartLabel(btn, isFav(slug));
      btn.hidden = false;
      btn.addEventListener('click', function () {
        var on = toggleFav(slug, btn.getAttribute('data-fav-name'));
        heartLabel(btn, on);
        tap();
      });
    });
  }
  function tap() { if (hasNative()) native('haptic').catch(function () {}); }

  window.WN = {
    inApp: inApp, hasNative: hasNative, native: native, onNative: onNative, statsUrl: STATS_URL,
    track: track, countOpen: countOpen, nyDay: nyDay, shareUrl: shareUrl, tap: tap,
    favs: { list: favList, has: isFav, toggle: toggleFav, sync: syncTags, restore: restoreFavs, limit: TAG_LIMIT },
    mountHearts: mountHearts, heartLabel: heartLabel,
  };

  if (inApp) document.documentElement.classList.add('in-app');
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { mountHearts(); });
  else mountHearts();
})();

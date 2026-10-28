// Word NYC stats: a Cloudflare Worker with a D1 database, free tier.
//
// Keeps daily totals for sponsor reports, with no cookies, IDs or IP addresses: the site and the app send
// { m: metric, p: "app" | "web", k: venue slug or source, f: 1 if first open of the day } and the worker adds
// one to that day's total. Deployed by .github/workflows/stats-worker.yml.
//
//   POST /e                  count an event (from wn.js; sendBeacon, text/plain)
//   GET  /followers?key=     current followers per venue (used by scraper/notify.py)
//   POST /push               noon-push delivery/open counts (from scraper/notify.py; Bearer STATS_KEY)
//   GET  /report.json?key=&month=YYYY-MM   the monthly summary shown by /app-stats.html

const SITE_ORIGINS = ['https://word-nyc.com', 'https://www.word-nyc.com'];
const VENUE_METRICS = new Set(['tix', 'stix', 'spv', 'spt', 'fav', 'unfav']);
const METRICS = new Set([...VENUE_METRICS, 'open', 'share']);
const SLUG = /^[a-z0-9][a-z0-9-]{0,79}$/;
const SHORT = /^[a-z0-9_-]{0,24}$/;

function nyDay(d = new Date()) {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' }).format(d);
}

function cors(request) {
  const origin = request.headers.get('Origin') || '';
  return {
    'Access-Control-Allow-Origin': SITE_ORIGINS.includes(origin) ? origin : SITE_ORIGINS[0],
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    'Access-Control-Max-Age': '86400',
    Vary: 'Origin',
  };
}

function json(data, request, status = 200) {
  return new Response(JSON.stringify(data, null, 1), {
    status, headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', ...cors(request) },
  });
}

function authorized(request, env, url) {
  if (!env.STATS_KEY) return false;
  const given = url.searchParams.get('key') || (request.headers.get('Authorization') || '').replace(/^Bearer\s+/i, '');
  if (given.length !== env.STATS_KEY.length) return false;
  let diff = 0;
  for (let i = 0; i < given.length; i++) diff |= given.charCodeAt(i) ^ env.STATS_KEY.charCodeAt(i);
  return diff === 0;
}

async function countEvent(request, env) {
  const origin = request.headers.get('Origin');
  if (origin && !SITE_ORIGINS.includes(origin)) return new Response(null, { status: 403 });
  const text = await request.text();
  if (text.length > 600) return new Response(null, { status: 413 });
  let e;
  try { e = JSON.parse(text); } catch { return new Response(null, { status: 400 }); }
  const m = String(e.m || ''), p = e.p === 'app' ? 'app' : 'web';
  let k = String(e.k || '').toLowerCase();
  if (!METRICS.has(m)) return new Response(null, { status: 400 });
  if (VENUE_METRICS.has(m) ? !SLUG.test(k) : !SHORT.test(k)) return new Response(null, { status: 400 });
  if (m === 'share' && !['show', 'map', 'story'].includes(k)) k = '';
  const first = m === 'open' && Number(e.f) === 1 ? 1 : 0;
  const day = nyDay();
  const stmts = [env.DB.prepare(
    `INSERT INTO counts (day, metric, plat, k, n, firsts) VALUES (?1, ?2, ?3, ?4, 1, ?5)
     ON CONFLICT (day, metric, plat, k) DO UPDATE SET n = n + 1, firsts = firsts + ?5`).bind(day, m, p, k, first)];
  if (m === 'fav' || m === 'unfav') {
    stmts.push(env.DB.prepare(
      `INSERT INTO followers (venue, n) VALUES (?1, MAX(?2, 0))
       ON CONFLICT (venue) DO UPDATE SET n = MAX(n + ?2, 0)`).bind(k, m === 'fav' ? 1 : -1));
  }
  await env.DB.batch(stmts);
  return new Response(null, { status: 204, headers: cors(request) });
}

async function savePushes(request, env) {
  const body = await request.json().catch(() => null);
  const rows = (body && Array.isArray(body.rows) ? body.rows : []).slice(0, 200);
  const now = new Date().toISOString();
  const stmts = rows.filter((r) => r && typeof r.id === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(r.day || '')).map((r) =>
    env.DB.prepare(
      `INSERT INTO pushes (id, day, kind, sponsor, fav, sent, opened, ios, updated) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)
       ON CONFLICT (id) DO UPDATE SET sent = ?6, opened = ?7, ios = ?8, updated = ?9`)
      .bind(r.id.slice(0, 64), r.day, String(r.kind || 'base').slice(0, 12), String(r.sponsor || '').slice(0, 80),
            String(r.fav || '').slice(0, 80), Number(r.sent) || 0, Number(r.opened) || 0, Number(r.ios) || 0, now));
  if (stmts.length) await env.DB.batch(stmts);
  return json({ saved: stmts.length }, request);
}

async function followers(env) {
  const { results } = await env.DB.prepare('SELECT venue, n FROM followers WHERE n > 0 ORDER BY n DESC').all();
  return Object.fromEntries(results.map((r) => [r.venue, r.n]));
}

async function report(request, env, url) {
  const month = /^\d{4}-\d{2}$/.test(url.searchParams.get('month') || '') ? url.searchParams.get('month') : nyDay().slice(0, 7);
  const like = `${month}-%`;
  const [counts, pushes, fans] = await Promise.all([
    env.DB.prepare('SELECT day, metric, plat, k, n, firsts FROM counts WHERE day LIKE ?1').bind(like).all(),
    env.DB.prepare('SELECT * FROM pushes WHERE day LIKE ?1 ORDER BY day').bind(like).all(),
    followers(env),
  ]);

  const days = {}, venues = {}, shares = { show: 0, map: 0, story: 0 };
  const dayRow = (d) => (days[d] ||= { day: d, opens_app: 0, opens_web: 0, users_app: 0, users_web: 0, push_opens: 0,
                                        push_sent: 0, push_opened: 0, sponsor: '' });
  const venue = (v) => (venues[v] ||= { venue: v, ticket_taps: 0, sponsored_views: 0, sponsored_taps: 0,
                                        sponsored_ticket_taps: 0, followers: 0, push_sent: 0, push_opened: 0 });
  for (const r of counts.results) {
    if (r.metric === 'open') {
      const d = dayRow(r.day);
      d[`opens_${r.plat}`] += r.n;
      d[`users_${r.plat}`] += r.firsts;
      if (r.k === 'push') d.push_opens += r.n;
    } else if (r.metric === 'tix') venue(r.k).ticket_taps += r.n;
    else if (r.metric === 'stix') { venue(r.k).sponsored_ticket_taps += r.n; venue(r.k).ticket_taps += r.n; }
    else if (r.metric === 'spv') venue(r.k).sponsored_views += r.n;
    else if (r.metric === 'spt') venue(r.k).sponsored_taps += r.n;
    else if (r.metric === 'share') shares[r.k] = (shares[r.k] || 0) + r.n;
  }
  let sent = 0, opened = 0, iosSent = 0;
  for (const p of pushes.results) {
    const d = dayRow(p.day);
    d.push_sent += p.sent; d.push_opened += p.opened;
    sent += p.sent; opened += p.opened; iosSent += p.ios;
    if (p.sponsor) {
      d.sponsor = p.sponsor;
      venue(p.sponsor).push_sent += p.sent;
      venue(p.sponsor).push_opened += p.opened;
    }
  }
  for (const [v, n] of Object.entries(fans)) venue(v).followers = n;

  const dayList = Object.values(days).sort((a, b) => a.day.localeCompare(b.day));
  const sum = (key) => dayList.reduce((s, d) => s + d[key], 0);
  const active = dayList.filter((d) => d.users_app + d.users_web > 0);
  const avg = (key) => (active.length ? Math.round(sum(key) / active.length) : 0);
  const peak = (key) => dayList.reduce((m, d) => Math.max(m, d[key]), 0);
  const rate = (o, s) => (s ? Math.round((o / s) * 1000) / 10 : null);

  return json({
    month,
    generated: new Date().toISOString(),
    notes: 'Daily totals only; no cookies, IDs or IP addresses. Daily users = devices opening the app or map for the first time that day.',
    totals: {
      opens: { app: sum('opens_app'), web: sum('opens_web') },
      daily_users_avg: { app: avg('users_app'), web: avg('users_web') },
      daily_users_peak: { app: peak('users_app'), web: peak('users_web') },
      push: { sent, opened, open_rate_pct: rate(opened, sent), ios_sent: iosSent, app_opens_from_push: sum('push_opens') },
      ticket_taps: Object.values(venues).reduce((s, v) => s + v.ticket_taps, 0),
      shares,
      followers_total: Object.values(fans).reduce((s, n) => s + n, 0),
    },
    days: dayList.map((d) => ({ ...d, push_open_rate_pct: rate(d.push_opened, d.push_sent) })),
    venues: Object.values(venues).sort((a, b) =>
      (b.sponsored_views + b.ticket_taps + b.followers) - (a.sponsored_views + a.ticket_taps + a.followers) || a.venue.localeCompare(b.venue)),
  }, request);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: cors(request) });
    try {
      if (url.pathname === '/e' && request.method === 'POST') return await countEvent(request, env);
      if (url.pathname === '/followers' && request.method === 'GET') {
        if (!authorized(request, env, url)) return json({ error: 'key' }, request, 401);
        return json({ followers: await followers(env) }, request);
      }
      if (url.pathname === '/push' && request.method === 'POST') {
        if (!authorized(request, env, url)) return json({ error: 'key' }, request, 401);
        return await savePushes(request, env);
      }
      if (url.pathname === '/report.json' && request.method === 'GET') {
        if (!authorized(request, env, url)) return json({ error: 'key' }, request, 401);
        return await report(request, env, url);
      }
      if (url.pathname === '/') return new Response('Word NYC stats\n', { headers: { 'Content-Type': 'text/plain' } });
      return new Response('Not found\n', { status: 404 });
    } catch (err) {
      return json({ error: String(err && err.message || err) }, request, 500);
    }
  },
};

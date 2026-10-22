"""Open venue calendar pages in a real (headless) browser and capture what a visitor would see.

For each venue we keep: the visible text, the links, any schema.org JSON-LD, iCal links, and whether
the site runs The Events Calendar for WordPress. If the page doesn't mention tonight's date we follow
the most likely "Calendar / Events / Shows" link once.
"""
from __future__ import annotations

import asyncio
import json
import re
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass, field
from datetime import date

from common import USER_AGENT, get, log

BROWSER_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/141.0.0.0 Safari/537.36 WordNYC/1.0 (+https://word-nyc.com)")
CALENDAR_WORDS = re.compile(r"calendar|events?\b|schedule|shows?\b|concerts?|performances?|what'?s on|"
                            r"line-?up|upcoming|season|music|tickets|jazz|live|program", re.I)
CLOCK = re.compile(r"\b\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)(?![a-z])|\b\d{1,2}:\d{2}\b", re.I)
BLOCK_SIGNS = re.compile(r"just a moment|verify you are human|access denied|attention required|"
                         r"are you a robot|captcha|request blocked|forbidden", re.I)
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september",
          "october", "november", "december"]
DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def tonight_pattern(night: date) -> re.Pattern:
    """Regex for the ways a page might write tonight's date."""
    mon, mo, d, wd = MONTHS[night.month - 1], night.month, night.day, DAYS[night.weekday()]
    parts = [
        rf"\b{mon[:3]}[a-z]*\.?,?\s+0?{d}(?:st|nd|rd|th)?\b",       # Oct 18 / October 18th
        rf"\b0?{d}(?:st|nd|rd|th)?\s+(?:of\s+)?{mon[:3]}[a-z]*\b",  # 18 Oct
        rf"\b0?{mo}[/.\-]0?{d}\b",                                  # 10/18
        rf"\b{night.isoformat()}\b",
        rf"\b{wd[:3]}[a-z]*\.?,?\s+0?{d}\b",                        # Sun 18 / Sunday 18
        r"\btoday\b", r"\btonight\b",
    ]
    return re.compile("|".join(parts), re.I)


@dataclass
class Snapshot:
    venue: str
    url: str
    final_url: str = ""
    status: int | None = None
    text: str = ""
    links: list[dict] = field(default_factory=list)
    jsonld: list[str] = field(default_factory=list)
    ical: list[str] = field(default_factory=list)
    tribe: bool = False
    blocked: bool = False
    error: str | None = None
    followed: str | None = None   # calendar link we followed from the first page
    tried: list = field(default_factory=list)  # (url, usable?) for calendar links tried
    first_links: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.error and not self.blocked and len(self.text) > 200


_robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}


def allowed(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    host = f"{parts.scheme}://{parts.netloc}"
    if host not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            rp.parse(get(f"{host}/robots.txt", timeout=15).splitlines())
            _robots[host] = rp
        except Exception:  # noqa: BLE001 - no robots.txt (or unreachable) means no restrictions
            _robots[host] = None
    rp = _robots[host]
    return True if rp is None else rp.can_fetch(USER_AGENT, url) and rp.can_fetch("WordNYC", url)


EXTRACT_JS = r"""
() => {
  const abs = (h) => { try { return new URL(h, location.href).href; } catch (e) { return ''; } };
  const seen = new Set(), links = [];
  for (const a of document.querySelectorAll('a[href]')) {
    const href = abs(a.getAttribute('href'));
    if (!href.startsWith('http') && !href.startsWith('webcal')) continue;
    const text = (a.innerText || a.getAttribute('aria-label') || a.title || '').replace(/\s+/g, ' ').trim().slice(0, 90);
    const key = href + '|' + text;
    if (seen.has(key)) continue;
    seen.add(key); links.push({ text, href });
    if (links.length >= 600) break;
  }
  const html = document.documentElement.innerHTML;
  return {
    text: document.body ? document.body.innerText : '',
    links,
    jsonld: [...document.querySelectorAll('script[type="application/ld+json"]')].map(s => s.textContent).slice(0, 40),
    tribe: /tribe-events|tribe_events|the-events-calendar/.test(html),
  };
}
"""


async def _capture(page, url: str, timeout_ms: int) -> dict:
    resp = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    try:
        await page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:  # noqa: BLE001 - busy pages never go idle; what loaded is enough
        pass
    try:  # trigger lazy-loaded listings
        await page.evaluate("window.scrollTo(0, document.body ? document.body.scrollHeight : 0)")
        await page.wait_for_timeout(1200)
    except Exception:  # noqa: BLE001
        pass
    data = await page.evaluate(EXTRACT_JS)
    for frame in page.frames[1:8]:  # embedded calendars (Google Calendar, ticketing widgets) live in iframes
        try:
            inner = await frame.evaluate("document.body ? document.body.innerText : ''")
            if inner and len(inner) > 40:
                data["text"] = (data["text"] or "") + "\n\n[embedded: " + frame.url[:120] + "]\n" + inner
        except Exception:  # noqa: BLE001
            pass
    data["status"] = resp.status if resp else None
    data["final_url"] = page.url
    return data


def _calendar_candidates(links: list[dict], base: str) -> list[str]:
    host = urllib.parse.urlsplit(base).netloc.replace("www.", "")
    scored = []
    for ln in links:
        href, text = ln["href"], ln["text"]
        if host not in urllib.parse.urlsplit(href).netloc or href.split("#")[0].rstrip("/") == base.rstrip("/"):
            continue
        score = 0
        if CALENDAR_WORDS.search(text):
            score += 2
        if CALENDAR_WORDS.search(urllib.parse.urlsplit(href).path):
            score += 1
        if re.search(r"calendar|events|schedule|shows|concerts", text + href, re.I):
            score += 1
        if score:
            scored.append((-score, len(href), href.split("#")[0]))
    out = []
    for _, _, h in sorted(scored):
        if h not in out:
            out.append(h)
    return out[:3]


async def _snapshot(browser, venue: dict, night: date, sem: asyncio.Semaphore, timeout_ms: int) -> Snapshot:
    url = venue["url"]
    snap = Snapshot(venue=venue["name"], url=url)
    async with sem:
        if not await asyncio.to_thread(allowed, url):
            snap.error = "robots.txt asks automated readers not to visit this page"
            return snap
        ctx = await browser.new_context(user_agent=BROWSER_UA, locale="en-US", timezone_id="America/New_York",
                                        viewport={"width": 400, "height": 1600} if venue.get("narrow")
                                        else {"width": 1280, "height": 1600}, ignore_https_errors=True)
        try:
            page = await ctx.new_page()

            async def block_heavy(route):
                if route.request.resource_type in ("image", "media", "font"):
                    await route.abort()
                else:
                    await route.continue_()
            await page.route("**/*", block_heavy)

            try:
                data = await _capture(page, url, timeout_ms)
            except Exception as first:  # noqa: BLE001 - one retry: flaky DNS/timeouts, or the other www form
                if not re.search(r"ERR_NAME_NOT_RESOLVED|ERR_CONNECTION|Timeout", str(first)):
                    raise
                parts = urllib.parse.urlsplit(url)
                host = parts.netloc[4:] if parts.netloc.startswith("www.") else "www." + parts.netloc
                await asyncio.sleep(3)
                try:
                    data = await _capture(page, url, timeout_ms)
                except Exception:  # noqa: BLE001
                    data = await _capture(page, parts._replace(netloc=host).geturl(), timeout_ms)
            pat = tonight_pattern(night)

            def usable(d) -> bool:  # names tonight AND shows clock times (a home page often lists dates only)
                t = d["text"] or ""
                return bool(pat.search(t) and CLOCK.search(t))

            first_links = data["links"]
            if not usable(data) and not venue.get("no_follow"):
                for cand in _calendar_candidates(data["links"], data["final_url"] or url):
                    if not await asyncio.to_thread(allowed, cand):
                        continue
                    try:
                        data2 = await _capture(page, cand, timeout_ms)
                    except Exception as e:  # noqa: BLE001
                        snap.tried.append((cand, f"error {type(e).__name__}"))
                        continue
                    snap.tried.append((cand, f"usable={usable(data2)} chars={len(data2['text'] or '')}"))
                    if usable(data2):
                        data2["links"] += data["links"][:100]
                        data2["jsonld"] += data["jsonld"]
                        data2["tribe"] = data2["tribe"] or data["tribe"]
                        data, snap.followed = data2, cand
                        break
            snap.first_links = first_links
            snap.final_url, snap.status = data["final_url"], data["status"]
            snap.text = (data["text"] or "")[:400_000]
            snap.links, snap.jsonld, snap.tribe = data["links"], data["jsonld"], data["tribe"]
            snap.ical = [ln["href"] for ln in data["links"]
                         if re.search(r"\.ics\b|webcal:|[?&]ical=1|outlook-ical|/ical/?$", ln["href"], re.I)][:3]
            if (snap.status or 200) in (401, 403, 406, 409, 429, 503) or (len(snap.text) < 1500 and BLOCK_SIGNS.search(snap.text)):
                snap.blocked = True
            elif (snap.status or 200) >= 400:
                snap.error = f"page returned HTTP {snap.status}"
        except Exception as e:  # noqa: BLE001
            snap.error = f"{type(e).__name__}: {str(e).splitlines()[0][:160]}"
        finally:
            await ctx.close()
    return snap


def _resolve(host: str) -> str | None:
    """Look a host up over DNS-over-HTTPS, for names the runner's own DNS fails on."""
    try:
        data = json.loads(get("https://dns.google/resolve", {"name": host, "type": "A"}, timeout=10))
    except Exception:  # noqa: BLE001
        return None
    ips = [a["data"] for a in data.get("Answer") or [] if a.get("type") == 1]
    return ips[0] if ips else None


async def _snapshot_all(venues: list[dict], night: date, concurrency: int, timeout_ms: int) -> dict[str, Snapshot]:
    from playwright.async_api import async_playwright
    sem = asyncio.Semaphore(concurrency)
    args = ["--disable-dev-shm-usage"]
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=args)
        try:
            snaps = {s.venue: s for s in await asyncio.gather(*[_snapshot(browser, v, night, sem, timeout_ms)
                                                                for v in venues])}
        finally:
            await browser.close()

        # Second chance for sites whose names didn't resolve: look them up elsewhere and pin the address.
        retry = [v for v in venues if "ERR_NAME_NOT_RESOLVED" in (snaps[v["name"]].error or "")]
        rules = []
        for v in retry:
            host = urllib.parse.urlsplit(v["url"]).netloc
            for h in {host, host[4:] if host.startswith("www.") else "www." + host}:
                ip = await asyncio.to_thread(_resolve, h)
                if ip:
                    rules.append(f"MAP {h} {ip}")
        if rules:
            log(f"  retrying {len(retry)} site(s) with DNS-over-HTTPS addresses: {'; '.join(rules)}")
            browser = await pw.chromium.launch(args=args + ["--host-resolver-rules=" + ", ".join(rules)])
            try:
                for s in await asyncio.gather(*[_snapshot(browser, v, night, sem, timeout_ms) for v in retry]):
                    log(f"    {s.venue}: {s.error or 'loaded'}")
                    snaps[s.venue] = s
            finally:
                await browser.close()
    return snaps


def snapshot_all(venues: list[dict], night: date, concurrency: int = 6, timeout_ms: int = 30000) -> dict[str, Snapshot]:
    try:
        import playwright  # noqa: F401
    except ImportError:
        log("  browser: Playwright isn't installed, so venue pages were skipped")
        return {}
    return asyncio.run(_snapshot_all(venues, night, concurrency, timeout_ms))

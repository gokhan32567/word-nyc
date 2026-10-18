"""Shared helpers: time windows, formatting, HTTP."""
from __future__ import annotations

import html
import http.cookiejar
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
ROLLOVER_HOUR = 5  # times before 5 AM belong to the previous night, matching the page
USER_AGENT = "WordNYC/1.0 (+https://word-nyc.com; daily lineup builder)"


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- time

def night_window(night: date) -> tuple[datetime, datetime]:
    start = datetime(night.year, night.month, night.day, ROLLOVER_HOUR, tzinfo=NY)
    return start, start + timedelta(days=1)


def current_night() -> date:
    return (datetime.now(NY) - timedelta(hours=ROLLOVER_HOUR)).date()


def in_night(dt: datetime, night: date) -> bool:
    start, end = night_window(night)
    return start <= dt.astimezone(NY) < end


def clock(dt: datetime) -> str:
    """datetime -> '8:00 PM' in New York time."""
    dt = dt.astimezone(NY)
    return f"{dt.hour % 12 or 12}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'}"


def clock_from_minutes(m: int) -> str:
    m %= 1440
    return f"{(m // 60) % 12 or 12}:{m % 60:02d} {'AM' if m < 720 else 'PM'}"


def parse_clock(s: str | None) -> int | None:
    """'8pm', '8:30 PM', '20:30', '8:30 p.m.' -> minutes after midnight."""
    if not s:
        return None
    t = s.strip().lower().replace(".", "")
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a|p)", t)
    if m:
        h = int(m.group(1)) % 12 + (12 if m.group(3)[0] == "p" else 0)
        return h * 60 + int(m.group(2) or 0)
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", t)
    if m and int(m.group(1)) < 24:
        return int(m.group(1)) * 60 + int(m.group(2))
    return None


def minutes(t: str | None) -> int:
    """'8:00 PM' -> minutes into the night (after-midnight times sort last)."""
    m = parse_clock(t)
    if m is None:
        return 99999
    return m + 1440 if m < ROLLOVER_HOUR * 60 else m


def parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    v = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        m = re.match(r"(\d{4}-\d{2}-\d{2})(?:[T ](\d{1,2}):(\d{2}))?", v)
        if not m:
            return None
        d = date.fromisoformat(m.group(1))
        dt = datetime(d.year, d.month, d.day, int(m.group(2) or 0), int(m.group(3) or 0))
    return dt if dt.tzinfo else dt.replace(tzinfo=NY)


def has_time(value: str) -> bool:
    return bool(re.search(r"[T ]\d{1,2}:\d{2}", value or ""))


# ---------------------------------------------------------------- text

def clean_text(value, limit: int = 420) -> str | None:
    if not value:
        return None
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value)))
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return None
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"
    return text


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def money(v: float, cur: str) -> str:
    s = f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"
    return f"${s}" if cur in ("", "USD") else f"{s} {cur}"


def price_label(lo, hi=None, cur: str = "USD") -> str | None:
    try:
        lo = float(lo) if lo not in (None, "") else None
        hi = float(hi) if hi not in (None, "") else None
    except (TypeError, ValueError):
        return None
    if lo is None and hi is None:
        return None
    lo = hi if lo is None else lo
    cur = (cur or "USD").upper()
    first = "Free" if lo == 0 else money(lo, cur)
    if hi is None or hi == lo:
        return first
    return f"{first}–{money(hi, cur)}"


def names_of(x) -> list[str]:
    """Names from a JSON-LD value that may be a string, a dict or a list of either."""
    items = x if isinstance(x, list) else [x]
    out = []
    for it in items:
        name = it.get("name") if isinstance(it, dict) else it
        name = html.unescape(str(name or "")).strip()
        if name and name not in out:
            out.append(name)
    return out


def address_of(a) -> str | None:
    if isinstance(a, list):
        a = a[0] if a else None
    if isinstance(a, str):
        return clean_text(a, 160)
    if isinstance(a, dict):
        parts = [a.get("streetAddress"), a.get("addressLocality"), a.get("addressRegion")]
        return ", ".join(str(p).strip() for p in parts if p) or None
    return None


def image_of(x) -> str | None:
    if isinstance(x, list):
        x = x[0] if x else None
    if isinstance(x, dict):
        x = x.get("url") or x.get("contentUrl")
    return x if isinstance(x, str) and x.startswith("http") else None


# ---------------------------------------------------------------- http

# keeps cookies between requests: some venue sites redirect in a loop without them
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def get(url: str, params: dict | None = None, timeout: int = 25, headers: dict | None = None) -> str:
    if params:
        url = f"{url}{'&' if '?' in url else '?'}{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/json,text/calendar;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        **(headers or {}),
    })
    last = None
    for attempt in range(3):
        try:
            with OPENER.open(req, timeout=timeout) as r:
                return r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429 or e.code >= 500:
                time.sleep(2 * (attempt + 1))
                continue
            raise
        except urllib.error.URLError as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise last  # type: ignore[misc]

"""Read tonight's shows off a venue's calendar page with Claude, then check every answer against the page.

The model must quote, word for word, where the page shows the date and the time of each show.
A show is kept only if:
  - both quotes really appear on the page,
  - the date quote names tonight (or tomorrow's early hours for a late set),
  - the time quote contains the start time it reported,
  - its title words appear on the page.
Performers, works and prices that don't appear on the page are dropped. Descriptions are the model's own
short summary and are dropped if they copy a long phrase from the page.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import date, timedelta

from common import ROLLOVER_HOUR, clock_from_minutes, norm, parse_clock
from browse import DAYS, MONTHS, Snapshot, tonight_pattern
from genres import GENRES

API_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/") + "/v1/messages"
MODEL = os.environ.get("AI_MODEL", "claude-haiku-5-5")
MAX_PAGE_CHARS = 24_000
STOPWORDS = {"the", "and", "with", "for", "feat", "featuring", "presents", "live", "at", "from", "of", "in",
             "on", "a", "an", "by", "plus", "special", "guest", "guests", "night", "show", "music", "concert", "trio",
             "quartet", "quintet", "band", "orchestra", "ensemble"}
GENERIC = re.compile(r"^(closed|private (event|party)|no show|dark|tbd|tba|sold out|cancel+ed|"
                     r"open|happy hour|brunch|dinner|reservations?)$", re.I)

TOOL = {
    "name": "report_events",
    "description": "Report the public performances this page lists for tonight.",
    "input_schema": {
        "type": "object",
        "properties": {
            "page_kind": {"type": "string",
                          "enum": ["calendar", "single_event", "no_events_tonight", "not_a_calendar", "unreadable"]},
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Show title exactly as written on the page."},
                        "performers": {"type": "array", "items": {"type": "string"},
                                       "description": "Performer names exactly as written. Empty if none listed."},
                        "start_time": {"type": "string", "description": "Start time like '8:00 PM'. One event per set/performance time."},
                        "end_time": {"type": ["string", "null"]},
                        "date_evidence": {"type": "string",
                                          "description": "Exact text copied from the page that shows this event's date (e.g. a date heading)."},
                        "time_evidence": {"type": "string",
                                          "description": "Exact text copied from the page that shows the start time."},
                        "price": {"type": ["string", "null"], "description": "Price exactly as shown, or null."},
                        "program": {"type": "array", "items": {"type": "string"},
                                    "description": "Works being performed, if the page lists them."},
                        "genre": {"type": "string", "enum": GENRES},
                        "description": {"type": ["string", "null"],
                                        "description": "At most 25 words in your own words. Factual, no hype, no copied sentences."},
                        "link_number": {"type": ["integer", "null"],
                                        "description": "Number of the link for this event's page or tickets, from the LINKS list."},
                        "public_performance": {"type": "boolean",
                                               "description": "False for private events, classes, tours, closures, brunch or dining."},
                    },
                    "required": ["title", "start_time", "date_evidence", "time_evidence", "genre", "public_performance"],
                },
            },
        },
        "required": ["page_kind", "events"],
    },
}

SYSTEM = """You read a New York venue's web page and report the live performances it lists for one specific night, for a public listings site.

Rules:
- Report only performances the page explicitly shows on the requested date. If unsure, leave it out. Never guess or fill in.
- Late sets after midnight that belong to the requested night count (the night runs until 5 AM).
- Each separate set or performance time is its own event (e.g. 7:30 PM and 9:30 PM sets are two events).
- Copy titles, names, times and prices exactly as written. date_evidence and time_evidence must be exact text copied from the page.
- Only report events at the named venue. If the page lists several venues, ignore the others.
- Write descriptions in your own words (max 25 words). Do not copy sentences from the page.
- If the page shows nothing for that night, return an empty events list with the right page_kind."""


# ---------------------------------------------------------------- page excerpt

def _squash(s: str) -> str:
    s = (s or "").lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip()


def excerpt(text: str, night: date) -> str:
    """The parts of the page around tonight's date (whole page if short)."""
    if len(text) <= MAX_PAGE_CHARS:
        return text
    lines = text.splitlines()
    pat = tonight_pattern(night)
    hits = [i for i, ln in enumerate(lines) if pat.search(ln)]
    if not hits:
        return text[:MAX_PAGE_CHARS]
    keep: set[int] = set(range(min(15, len(lines))))
    for i in hits:
        keep.update(range(max(0, i - 4), min(len(lines), i + 70)))
    out, size, prev = [], 0, -2
    for i in sorted(keep):
        if i != prev + 1:
            out.append("…")
        out.append(lines[i])
        size += len(lines[i]) + 1
        prev = i
        if size > MAX_PAGE_CHARS:
            break
    return "\n".join(out)


def link_list(snap: Snapshot, page_excerpt: str, limit: int = 150) -> list[dict]:
    skip = re.compile(r"facebook|instagram|twitter|x\.com|tiktok|youtube|spotify|apple\.com|mailto:|tel:|google\.com/maps|"
                      r"linkedin|pinterest|privacy|cookie|terms|newsletter|login|cart|donate|careers|press", re.I)
    ex = page_excerpt.lower()
    ranked = []
    for ln in snap.links:
        if skip.search(ln["href"]) or not ln["text"]:
            continue
        score = 2 if ln["text"].lower()[:40] in ex else 0
        score += 1 if re.search(r"ticket|event|show|buy|reserve|book|rsvp|calendar|concert", ln["text"] + ln["href"], re.I) else 0
        ranked.append((-score, len(ranked), ln))
    return [ln for _, _, ln in sorted(ranked)[:limit]]


# ---------------------------------------------------------------- checks

def _date_regex(d: date) -> re.Pattern:
    mon, wd = MONTHS[d.month - 1], DAYS[d.weekday()]
    return re.compile("|".join([
        rf"\b{mon[:3]}[a-z]*\.?,?\s+0?{d.day}(?:st|nd|rd|th)?\b",
        rf"\b0?{d.day}(?:st|nd|rd|th)?\s+(?:of\s+)?{mon[:3]}[a-z]*\b",
        rf"\b0?{d.month}[/.\-]0?{d.day}\b",
        rf"\b{d.isoformat()}\b",
        rf"\b{wd[:3]}[a-z]*\.?,?\s+0?{d.day}\b",
        rf"\b0?{d.day}\s+{wd[:3]}[a-z]*\b",
    ]), re.I)


def which_night(evidence: str, night: date) -> str | None:
    """'tonight' if the quote names tonight's date, 'next' if tomorrow's, else None."""
    if re.search(r"\b(today|tonight)\b", evidence, re.I) or _date_regex(night).search(evidence):
        return "tonight"
    if _date_regex(night + timedelta(days=1)).search(evidence):
        return "next"
    return None


TIME_RE = re.compile(r"(?<![\d/$.,])(\d{1,2})(?::(\d{2}))?\s*(a\.?\s?m\.?|p\.?\s?m\.?|am|pm)?(?![\d/%])", re.I)


def times_in(evidence: str) -> set[int]:
    found = [(int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower().replace(".", "").replace(" ", ""),
              bool(m.group(2))) for m in TIME_RE.finditer(evidence)]
    out: set[int] = set()
    for i, (h, mi, mer, has_colon) in enumerate(found):
        if not mer:  # "8 & 10pm": take the meridian of the next time that has one
            mer = next((m for _, _, m, _ in found[i + 1:] if m), "")
        if mer and 1 <= h <= 12:
            out.add((h % 12 + (12 if mer.startswith("p") else 0)) * 60 + mi)
        elif has_colon and 13 <= h <= 23:
            out.add(h * 60 + mi)
        elif not mer and 1 <= h <= 11 and (has_colon or re.search(r"\b(shows?|doors|sets?|starts?|begins?|at)\b", evidence, re.I)):
            out.add((h + 12) * 60 + mi)  # evening listing without am/pm
    return out


WORD = re.compile(r"[^\W_]+", re.UNICODE)
# words too common in concert listings to prove anything on their own
GENERIC_MUSIC = {"symphony", "concerto", "sonata", "quartet", "quintet", "trio", "suite", "major", "minor", "opus",
                 "op", "no", "string", "piano", "violin", "cello", "works", "music", "songs", "selections", "program",
                 "premiere", "world", "new", "solo", "duo", "chamber", "orchestra", "choir", "mass", "requiem"}


def significant(s: str) -> list[str]:
    return [t for t in WORD.findall(s.lower()) if len(t) >= 3 and t not in STOPWORDS]


def words_on_page(item: str, page: str) -> bool:
    """At least half the item's words, including a distinctive one (not just 'symphony'), are on the page."""
    words = significant(item)
    if not words:
        return False
    present = [w for w in words if w in page]
    distinctive = [w for w in present if w not in GENERIC_MUSIC]
    return bool(distinctive) and len(present) >= len(words) / 2


def copied_phrase(desc: str, page_words: str, n: int = 8) -> bool:
    words = WORD.findall(desc.lower())
    return any(" ".join(words[i:i + n]) in page_words for i in range(0, max(0, len(words) - n + 1)))


def check(raw: dict, snap: Snapshot, links: list[dict], night: date, venue: dict, page: str, page_norm: str) -> tuple[dict | None, str]:
    title = (raw.get("title") or "").strip()
    if not raw.get("public_performance", True) or not title or GENERIC.match(title):
        return None, "not a public performance"
    de, te = raw.get("date_evidence") or "", raw.get("time_evidence") or ""
    if not (2 <= len(de) <= 200 and _squash(de) in page):
        return None, "date quote not found on page"
    if not (2 <= len(te) <= 200 and _squash(te) in page):
        return None, "time quote not found on page"
    start = parse_clock(raw.get("start_time"))
    if start is None or start not in times_in(te):
        return None, "start time not in time quote"
    which = which_night(de, night)
    late = start < ROLLOVER_HOUR * 60
    if which is None or (which == "next" and not late):
        return None, "date quote is not tonight"
    words = significant(title)
    present = [w for w in words if w in page]
    if words and (not present or (len(words) >= 3 and len(present) < len(words) / 2)):
        return None, "title not on page"
    page_words = " ".join(WORD.findall(page))

    performers = [p.strip() for p in raw.get("performers") or [] if p.strip() and norm(p) and norm(p) in page_norm]
    program = [w.strip() for w in raw.get("program") or [] if w.strip() and words_on_page(w, page)]
    price = (raw.get("price") or "").strip() or None
    if price and not (all(n in page for n in re.findall(r"\d+(?:\.\d+)?", price)) and
                      (re.search(r"\d", price) or "free" in page)):
        price = None
    desc = (raw.get("description") or "").strip() or None
    if desc and (len(desc) > 240 or copied_phrase(desc, page_words)):
        desc = None
    end = parse_clock(raw.get("end_time"))
    idx = raw.get("link_number")
    url = links[idx]["href"] if isinstance(idx, int) and 0 <= idx < len(links) else (snap.final_url or snap.url)
    day = night + timedelta(days=1) if late else night
    genre = raw.get("genre") if raw.get("genre") in GENRES else venue.get("genre", "Other")
    return {
        "title": title[:140], "performers": performers[:8], "venue": venue["name"],
        "address": venue.get("address"), "lat": venue["lat"], "lng": venue["lng"],
        "date": day.isoformat(), "time": clock_from_minutes(start),
        "end": clock_from_minutes(end) if end is not None and end != start else None,
        "url": url, "genre": genre, "subgenre": None, "price": price[:60] if price else None,
        "program": program[:12], "description": desc, "image": None,
        "source": "venue-ai", "listing_url": snap.final_url or snap.url,
    }, "ok"


# ---------------------------------------------------------------- API

class AIError(Exception):
    pass


def call_claude(api_key: str, prompt: str, max_tokens: int = 3000) -> tuple[dict, dict]:
    body = json.dumps({
        "model": MODEL, "max_tokens": max_tokens, "system": SYSTEM,
        "messages": [{"role": "user", "content": prompt}],
        "tools": [TOOL], "tool_choice": {"type": "tool", "name": "report_events"},
    }).encode()
    for attempt in range(5):
        req = urllib.request.Request(API_URL, data=body, method="POST", headers={
            "x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.loads(r.read())
            for block in data.get("content", []):
                if block.get("type") == "tool_use":
                    return block.get("input") or {}, data.get("usage") or {}
            raise AIError("no structured answer in the reply")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code in (429, 500, 502, 503, 529) and attempt < 4:
                wait = float(e.headers.get("retry-after") or 0) or 5 * (attempt + 1)
                time.sleep(min(wait, 60))
                continue
            raise AIError(f"API error {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            if attempt < 4:
                time.sleep(5 * (attempt + 1))
                continue
            raise AIError(f"API unreachable: {e}") from e
    raise AIError("API kept failing")


def extract(snap: Snapshot, venue: dict, night: date, api_key: str) -> tuple[list[dict], dict]:
    page_excerpt = excerpt(snap.text, night)
    links = link_list(snap, page_excerpt)
    weekday = DAYS[night.weekday()].capitalize()
    nice = f"{weekday}, {MONTHS[night.month - 1].capitalize()} {night.day}, {night.year}"
    note = f"\nNote about this page: {venue['note']}" if venue.get("note") else ""
    prompt = (
        f"Venue: {venue['name']} ({venue.get('address', 'New York')})\n"
        f"Page: {snap.final_url or snap.url}\n"
        f"Night to report: {nice} (from 5 AM that day until 5 AM the next morning){note}\n\n"
        f"PAGE TEXT:\n<<<\n{page_excerpt}\n>>>\n\n"
        "LINKS (number: text -> url):\n" +
        "\n".join(f"{i}: {ln['text'][:70]} -> {ln['href'][:160]}" for i, ln in enumerate(links))
    )
    answer, usage = call_claude(api_key, prompt)
    page = _squash(snap.text)
    page_norm = norm(snap.text)
    kept, reasons = [], {}
    for raw in answer.get("events") or []:
        ev, why = check(raw, snap, links, night, venue, page, page_norm)
        if ev:
            kept.append(ev)
        else:
            reasons[why] = reasons.get(why, 0) + 1
    return kept, {"page_kind": answer.get("page_kind"), "proposed": len(answer.get("events") or []),
                  "rejected": reasons, "input_tokens": usage.get("input_tokens", 0),
                  "output_tokens": usage.get("output_tokens", 0)}

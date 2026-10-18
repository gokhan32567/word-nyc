"""Structured sources: schema.org JSON-LD, The Events Calendar (WordPress), iCal, Eventbrite, form submissions.

Every reader returns events in the shared format and keeps only shows starting tonight
(5:00 AM to 5:00 AM New York time).
"""
from __future__ import annotations

import csv
import html
import io
import json
import re
import urllib.parse
from datetime import date, datetime, timedelta

from common import (NY, address_of, clean_text, clock, get, has_time, image_of, in_night,
                    names_of, night_window, parse_clock, parse_iso, price_label)
from genres import GENRES, bucket
from shows import same_place

EVENT_TYPES = {"event", "musicevent", "comedyevent", "theaterevent", "danceevent", "festival",
               "socialevent", "educationevent", "screeningevent"}


def base_event(venue: dict, **kw) -> dict:
    ev = {
        "title": "TBA", "performers": [], "venue": venue["name"], "address": venue.get("address"),
        "lat": venue["lat"], "lng": venue["lng"], "date": None, "time": None, "end": None,
        "url": venue.get("url"), "genre": venue.get("genre", "Other"), "subgenre": None, "price": None,
        "program": [], "description": None, "image": None, "source": "venue",
        "listing_url": venue.get("url"),
    }
    ev.update(kw)
    return ev


def _date_time(when: datetime, raw: str) -> tuple[str, str | None]:
    local = when.astimezone(NY)
    return local.date().isoformat(), (clock(local) if has_time(raw) else None)


# ---------------------------------------------------------------- JSON-LD

def walk_ld(node):
    """Yield every dict in a JSON-LD blob (handles @graph, lists, nested objects)."""
    if isinstance(node, list):
        for n in node:
            yield from walk_ld(n)
    elif isinstance(node, dict):
        yield node
        for k in ("@graph", "itemListElement", "item", "subEvent", "event", "events"):
            if k in node:
                yield from walk_ld(node[k])


def is_event(d: dict) -> bool:
    t = d.get("@type", "")
    types = t if isinstance(t, list) else [t]
    return any(str(x).lower() in EVENT_TYPES for x in types)


def offers_price(offers) -> str | None:
    items = offers if isinstance(offers, list) else [offers]
    vals, cur = [], "USD"
    for o in items:
        if not isinstance(o, dict):
            continue
        cur = o.get("priceCurrency") or cur
        for k in ("price", "lowPrice", "highPrice"):
            try:
                if o.get(k) not in (None, ""):
                    vals.append(float(str(o[k]).replace("$", "").replace(",", "")))
            except ValueError:
                pass
    return price_label(min(vals), max(vals), cur) if vals else None


def location_of(loc) -> tuple[str | None, str | None, str | None]:
    """(name, address, state) from a schema.org location: a Place, a list of them, or plain text."""
    if isinstance(loc, list):
        loc = next((x for x in loc if isinstance(x, (dict, str))), None)
    if isinstance(loc, str):
        parts = [p.strip() for p in loc.split(",") if p.strip()]
        while parts and re.fullmatch(r"(usa|us|united states( of america)?)", parts[-1], re.I):
            parts.pop()
        if not parts:
            return None, None, None
        region = parts[-1].split()[0] if len(parts) >= 3 else None
        return parts[0], ", ".join(parts[1:]) or None, region
    if isinstance(loc, dict):
        addr = loc.get("address")
        region = addr.get("addressRegion") if isinstance(addr, dict) else None
        return (names_of(loc.get("name")) or [None])[0], address_of(addr), region
    return None, None, None


def jsonld_events(blobs: list[str], venue: dict, night: date, page_url: str) -> list[dict]:
    out = []
    for blob in blobs:
        try:
            data = json.loads(html.unescape(blob.strip()))
        except (json.JSONDecodeError, ValueError):
            continue
        for d in walk_ld(data):
            if not is_event(d):
                continue
            raw_start = str(d.get("startDate", ""))
            when = parse_iso(raw_start)
            if not when or not has_time(raw_start) or not in_night(when, night):
                continue
            status = str(d.get("eventStatus", "")).lower()
            if "cancel" in status or "postpon" in status:
                continue
            raw_end = str(d.get("endDate", ""))
            end_dt = parse_iso(raw_end)
            raw_genre = d.get("genre") or ""
            if isinstance(raw_genre, list):
                raw_genre = ", ".join(map(str, raw_genre))
            performers = names_of(d.get("performer"))
            title = (names_of(d.get("name")) or performers or ["TBA"])[0]
            loc_name, loc_address, region = location_of(d.get("location"))
            if same_place(venue, loc_name, loc_address, region) is False:
                continue  # a promoter's page listing shows at its other venues or in other cities
            day, t = _date_time(when, raw_start)
            out.append(base_event(
                venue, title=title, performers=performers,
                address=loc_address or venue.get("address"),
                date=day, time=t,
                end=clock(end_dt) if end_dt and has_time(raw_end) and end_dt > when else None,
                url=d.get("url") if str(d.get("url", "")).startswith("http") else page_url,
                genre=bucket(str(raw_genre), venue.get("genre", "")) if raw_genre else venue.get("genre", "Other"),
                subgenre=clean_text(raw_genre, 60), price=offers_price(d.get("offers")),
                program=names_of(d.get("workPerformed")), image=image_of(d.get("image")),
                source="venue-data", listing_url=page_url,
                _hint=f"{d.get('@type', '')} {raw_genre}",
            ))
    return out


# ---------------------------------------------------------------- The Events Calendar (WordPress)

def tribe_events(site_url: str, venue: dict, night: date) -> list[dict]:
    """WordPress sites running The Events Calendar expose a public REST API."""
    origin = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(site_url))
    start, end = night_window(night)
    data = json.loads(get(f"{origin}/wp-json/tribe/events/v1/events", {
        "start_date": start.strftime("%Y-%m-%d %H:%M:%S"),
        "end_date": (end - timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S"),
        "per_page": 50,
    }))
    out = []
    for e in data.get("events", []):
        if e.get("all_day"):
            continue
        when = parse_iso(str(e.get("start_date", "")))
        if not when or not in_night(when, night):
            continue
        place = e.get("venue") if isinstance(e.get("venue"), dict) else {}
        if same_place(venue, html.unescape(place.get("venue") or ""),
                      " ".join(filter(None, [place.get("address"), place.get("city")])),
                      place.get("stateprovince") or place.get("state") or place.get("province")) is False:
            continue  # the same site's calendar for another location
        end_dt = parse_iso(str(e.get("end_date", "")))
        cats = ", ".join(c.get("name", "") for c in e.get("categories") or [])
        day, t = _date_time(when, str(e.get("start_date")))
        out.append(base_event(
            venue, title=html.unescape(e.get("title") or "TBA"), date=day, time=t,
            end=clock(end_dt) if end_dt and end_dt > when else None,
            url=e.get("url") or site_url,
            genre=bucket(cats, venue.get("genre", "")) if cats else venue.get("genre", "Other"),
            subgenre=clean_text(cats, 60), price=clean_text(e.get("cost"), 40),
            image=image_of((e.get("image") or {}).get("url")) if isinstance(e.get("image"), dict) else None,
            source="venue-data", listing_url=site_url, _hint=cats,
        ))
    return out


# ---------------------------------------------------------------- iCal

def _ics_unescape(s: str) -> str:
    return s.replace("\\n", " ").replace("\\N", " ").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\").strip()


def _ics_time(value: str, params: str) -> tuple[datetime | None, bool]:
    """Returns (datetime, has_time)."""
    v = value.strip()
    if "VALUE=DATE" in params.upper() or re.fullmatch(r"\d{8}", v):
        return None, False
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})?(Z)?", v)
    if not m:
        return None, False
    y, mo, d, h, mi = (int(m.group(i)) for i in range(1, 6))
    if m.group(7):
        from datetime import timezone
        return datetime(y, mo, d, h, mi, tzinfo=timezone.utc), True
    tz = NY
    tzm = re.search(r"TZID=([^;:]+)", params)
    if tzm:
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(tzm.group(1).strip('"'))
        except Exception:  # noqa: BLE001
            tz = NY
    return datetime(y, mo, d, h, mi, tzinfo=tz), True


def ical_events(url: str, venue: dict, night: date) -> list[dict]:
    text = get(url.replace("webcal://", "https://"))
    lines = re.sub(r"\r?\n[ \t]", "", text).splitlines()  # unfold
    out, cur = [], None
    for line in lines:
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT" and cur is not None:
            start, timed = _ics_time(cur.get("DTSTART", ("", ""))[1], cur.get("DTSTART", ("", ""))[0])
            if start and timed and in_night(start, night) and "CANCEL" not in cur.get("STATUS", ("", ""))[1].upper():
                end, _ = _ics_time(cur.get("DTEND", ("", ""))[1], cur.get("DTEND", ("", ""))[0])
                local = start.astimezone(NY)
                out.append(base_event(
                    venue, title=_ics_unescape(cur.get("SUMMARY", ("", "TBA"))[1]) or "TBA",
                    date=local.date().isoformat(), time=clock(local),
                    end=clock(end) if end and end > start else None,
                    url=cur.get("URL", ("", ""))[1].strip() or venue.get("url"),
                    description=None, source="venue-data", listing_url=venue.get("url"),
                ))
            cur = None
        elif cur is not None and ":" in line:
            key, value = line.split(":", 1)
            name, _, params = key.partition(";")
            cur[name.upper()] = (params, value)
    return out


# ---------------------------------------------------------------- Eventbrite (organizer pages)

def eventbrite_events(organizer_id: str, token: str, venue: dict, night: date) -> list[dict]:
    data = json.loads(get(f"https://www.eventbriteapi.com/v3/organizers/{organizer_id}/events/",
                          {"status": "live", "order_by": "start_asc", "time_filter": "current_future",
                           "expand": "ticket_availability"},
                          headers={"Authorization": f"Bearer {token}"}))
    out = []
    for e in data.get("events", []):
        when = parse_iso((e.get("start") or {}).get("local", ""))
        if not when or not in_night(when, night):
            continue
        tav = e.get("ticket_availability") or {}
        lo = ((tav.get("minimum_ticket_price") or {}).get("major_value"))
        hi = ((tav.get("maximum_ticket_price") or {}).get("major_value"))
        out.append(base_event(
            venue, title=(e.get("name") or {}).get("text") or "TBA",
            date=when.date().isoformat(), time=clock(when),
            url=e.get("url") or venue.get("url"),
            price="Free" if e.get("is_free") else price_label(lo, hi),
            image=image_of((e.get("logo") or {}).get("url")), source="venue-data",
        ))
    return out


# ---------------------------------------------------------------- "Submit your show" form (Google Sheet CSV)

TRUTHY = {"yes", "y", "true", "x", "approved", "ok", "1", "✓", "✔"}


def _col(row: dict, *names: str) -> str:
    for k, v in row.items():
        if k and any(n in k.lower() for n in names):
            return (v or "").strip()
    return ""


def submission_events(csv_url: str, night: date, geocode) -> list[dict]:
    """Rows from the published submissions sheet that are approved and happen tonight."""
    rows = csv.DictReader(io.StringIO(get(csv_url)))
    out = []
    for row in rows:
        if _col(row, "approved").lower() not in TRUTHY:
            continue
        raw_date = _col(row, "date")
        try:
            d = datetime.strptime(raw_date, "%m/%d/%Y").date() if "/" in raw_date else date.fromisoformat(raw_date)
        except ValueError:
            continue
        t = parse_clock(_col(row, "start time", "time"))
        if t is None:
            continue
        start = datetime(d.year, d.month, d.day, t // 60, t % 60, tzinfo=NY)
        if not in_night(start, night):
            continue
        venue_name, address = _col(row, "venue name", "venue"), _col(row, "address")
        loc = geocode(address or venue_name)
        if not loc:
            continue
        genre = _col(row, "genre")
        out.append({
            "title": _col(row, "show", "title") or "TBA",
            "performers": [p.strip() for p in re.split(r"[;,]", _col(row, "performer")) if p.strip()],
            "venue": venue_name, "address": address or None, "lat": loc[0], "lng": loc[1],
            "date": start.date().isoformat(), "time": clock(start), "end": None,
            "url": _col(row, "ticket", "link") or None,
            "genre": genre if genre in GENRES else bucket(genre),
            "subgenre": None, "price": _col(row, "price") or None, "program": [],
            "description": clean_text(_col(row, "description"), 300), "image": None,
            "source": "submission",
        })
    return out

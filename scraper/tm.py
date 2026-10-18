"""Ticketmaster Discovery API (also covers TicketWeb and Universe venues)."""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone

from common import NY, clean_text, clock, get, money, night_window, parse_iso, price_label
from genres import VAGUE, bucket

CENTER = (40.7300, -73.9950)   # lower Manhattan
RADIUS_MILES = 12              # covers Manhattan, most of Brooklyn and Queens

_GH = "0123456789bcdefghjkmnpqrstuvwxyz"


def geohash(lat: float, lng: float, precision: int = 9) -> str:
    lat_r, lng_r, bits, out, ch, even = [-90.0, 90.0], [-180.0, 180.0], 0, [], 0, True
    while len(out) < precision:
        rng, val = (lng_r, lng) if even else (lat_r, lat)
        mid = (rng[0] + rng[1]) / 2
        if val >= mid:
            ch = (ch << 1) | 1
            rng[0] = mid
        else:
            ch <<= 1
            rng[1] = mid
        even, bits = not even, bits + 1
        if bits == 5:
            out.append(_GH[ch])
            bits, ch = 0, 0
    return "".join(out)


def utc_param(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def from_ticketmaster(night: date, api_key: str) -> list[dict]:
    start, end = night_window(night)
    events, page = [], 0
    while True:
        data = json.loads(get("https://app.ticketmaster.com/discovery/v2/events.json", {
            "apikey": api_key,
            # music plus the performing arts the site covers (opera, ballet, classical, dance)
            "classificationName": "Music,Classical,Opera,Ballet,Dance",
            "geoPoint": geohash(*CENTER),
            "radius": RADIUS_MILES,
            "unit": "miles",
            "startDateTime": utc_param(start),
            "endDateTime": utc_param(end),
            "size": 200,
            "page": page,
            "sort": "date,asc",
        }))
        for e in data.get("_embedded", {}).get("events", []):
            ev = tm_event(e)
            if ev:
                events.append(ev)
        info = data.get("page", {})
        page += 1
        if page >= info.get("totalPages", 0) or page * 200 >= 1000:  # API cap: size * page < 1000
            break
        time.sleep(0.25)  # stay under 5 requests/second
    return events


def tm_image(images: list) -> str | None:
    wide = [i for i in images or [] if i.get("ratio") == "16_9" and i.get("width", 0) >= 600]
    pick = min(wide, key=lambda i: i["width"]) if wide else (images[0] if images else None)
    return pick.get("url") if pick else None


def tm_price(pr: dict) -> str | None:
    """Ticketmaster uses 0 for 'no price on file', so a 0 is dropped rather than shown as Free."""
    def num(x):
        try:
            return float(x) if x not in (None, "") and float(x) > 0 else None
        except (TypeError, ValueError):
            return None
    lo, hi = num(pr.get("min")), num(pr.get("max"))
    if lo is None and hi is None:
        return None
    if lo is None:
        return f"Up to {money(hi, (pr.get('currency') or 'USD').upper())}"
    return price_label(lo, hi, pr.get("currency", "USD"))


def tm_event(e: dict) -> dict | None:
    venues = e.get("_embedded", {}).get("venues") or []
    if not venues:
        return None
    v = venues[0]
    loc = v.get("location") or {}
    try:
        lat, lng = float(loc["latitude"]), float(loc["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    if e.get("dates", {}).get("status", {}).get("code") in {"cancelled", "canceled", "postponed"}:
        return None
    if (v.get("state") or {}).get("stateCode", "NY") != "NY":  # the radius reaches into New Jersey
        return None
    st = e.get("dates", {}).get("start", {})
    when = parse_iso(st.get("dateTime", "")) if st.get("dateTime") else None
    t = clock(when) if when and not st.get("timeTBA") and not st.get("noSpecificTime") else None
    c = (e.get("classifications") or [{}])[0]
    sub = (c.get("subGenre") or {}).get("name", "") or ""
    gen = (c.get("genre") or {}).get("name", "") or ""
    performers = [a["name"] for a in e.get("_embedded", {}).get("attractions") or [] if a.get("name")]
    title = e.get("name") or (performers[0] if performers else "TBA")
    addr = v.get("address") or {}
    address = ", ".join(x for x in [addr.get("line1"), (v.get("city") or {}).get("name"),
                                    (v.get("state") or {}).get("stateCode")] if x) or None
    pr = (e.get("priceRanges") or [{}])[0]
    return {
        "title": title,
        "performers": performers,
        "venue": v.get("name", ""),
        "address": address,
        "lat": round(lat, 5),
        "lng": round(lng, 5),
        "date": st.get("localDate") or (when.astimezone(NY).date().isoformat() if when else None),
        "time": t,
        "end": None,
        "url": e.get("url"),
        "genre": bucket(sub, gen, title),
        "subgenre": next((x for x in (sub, gen) if x.strip().lower() not in VAGUE), None),
        "price": tm_price(pr),
        "program": [],
        "description": clean_text(e.get("info") or e.get("description") or e.get("pleaseNote")),
        "image": tm_image(e.get("images") or []),
        "source": "ticketmaster",
    }

"""Coordinates for venues: OpenStreetMap Nominatim lookups, cached in geocache.json."""
from __future__ import annotations

import json
import math
import time

from common import HERE, get, log

CACHE_PATH = HERE / "geocache.json"
NYC_BOX = (40.47, 40.93, -74.27, -73.68)  # south, north, west, east


def in_nyc(lat: float, lng: float) -> bool:
    s, n, w, e = NYC_BOX
    return s <= lat <= n and w <= lng <= e


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 6371000 * 2 * math.asin(math.sqrt(h))


class Geocoder:
    """Looks up addresses once and remembers them (Nominatim allows 1 request per second)."""

    def __init__(self):
        try:
            self.cache = json.loads(CACHE_PATH.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            self.cache = {}
        self.dirty = False
        self.last = 0.0

    def __call__(self, query: str) -> tuple[float, float] | None:
        q = (query or "").strip()
        if not q:
            return None
        if q in self.cache:
            hit = self.cache[q]
            return tuple(hit) if hit else None
        wait = 1.1 - (time.time() - self.last)
        if wait > 0:
            time.sleep(wait)
        self.last = time.time()
        result = None
        try:
            rows = json.loads(get("https://nominatim.openstreetmap.org/search",
                                  {"q": q if "NY" in q or "New York" in q else f"{q}, New York, NY",
                                   "format": "json", "limit": 1, "countrycodes": "us"}))
            if rows:
                lat, lng = round(float(rows[0]["lat"]), 5), round(float(rows[0]["lon"]), 5)
                result = (lat, lng) if in_nyc(lat, lng) else None
        except Exception as e:  # noqa: BLE001
            log(f"  geocode failed for {q!r}: {e}")
            return None  # don't cache network errors
        self.cache[q] = list(result) if result else None
        self.dirty = True
        return result

    def save(self) -> None:
        if self.dirty:
            CACHE_PATH.write_text(json.dumps(self.cache, indent=1, sort_keys=True, ensure_ascii=False) + "\n")


def place_venues(venues: list[dict], geocode: Geocoder) -> list[dict]:
    """Fill in lat/lng from the address where missing; drop venues that can't be placed."""
    placed = []
    for v in venues:
        if not (isinstance(v.get("lat"), (int, float)) and isinstance(v.get("lng"), (int, float))):
            loc = geocode(v.get("address") or v["name"])
            if not loc:
                log(f"  {v['name']}: no map location for {v.get('address')!r}, skipped")
                v["_status"] = "no-location"
                continue
            v["lat"], v["lng"] = loc
        placed.append(v)
    return placed

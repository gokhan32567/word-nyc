"""Neighborhoods and boroughs for venues, from the ZIP code in their address.

Used by pages.py for the /neighborhood/ pages, venue intros and "nearby" links.
Edit OVERRIDES to fix a venue the ZIP code places wrongly.
"""
from __future__ import annotations

import re

# ZIP -> (neighborhood, borough)
ZIPS = {
    # Manhattan
    "10001": ("Chelsea", "Manhattan"), "10011": ("Chelsea", "Manhattan"),
    "10002": ("Lower East Side", "Manhattan"),
    "10003": ("East Village", "Manhattan"), "10009": ("East Village", "Manhattan"),
    "10006": ("Lower Manhattan", "Manhattan"), "10007": ("Lower Manhattan", "Manhattan"),
    "10013": ("Lower Manhattan", "Manhattan"),
    "10010": ("Flatiron & Gramercy", "Manhattan"), "10016": ("Murray Hill", "Manhattan"),
    "10012": ("Greenwich Village", "Manhattan"), "10014": ("Greenwich Village", "Manhattan"),
    "10018": ("Midtown", "Manhattan"), "10019": ("Midtown", "Manhattan"), "10020": ("Midtown", "Manhattan"),
    "10022": ("Midtown", "Manhattan"), "10036": ("Midtown", "Manhattan"), "10112": ("Midtown", "Manhattan"),
    "10017": ("Midtown", "Manhattan"),
    "10021": ("Upper East Side", "Manhattan"), "10028": ("Upper East Side", "Manhattan"),
    "10065": ("Upper East Side", "Manhattan"), "10075": ("Upper East Side", "Manhattan"),
    "10128": ("Upper East Side", "Manhattan"),
    "10023": ("Upper West Side", "Manhattan"), "10024": ("Upper West Side", "Manhattan"),
    "10025": ("Upper West Side", "Manhattan"),
    "10026": ("Harlem", "Manhattan"), "10027": ("Harlem", "Manhattan"), "10030": ("Harlem", "Manhattan"),
    "10031": ("Harlem", "Manhattan"), "10037": ("Harlem", "Manhattan"), "10039": ("Harlem", "Manhattan"),
    # Brooklyn
    "11201": ("Downtown Brooklyn & DUMBO", "Brooklyn"),
    "11206": ("Williamsburg", "Brooklyn"), "11211": ("Williamsburg", "Brooklyn"), "11249": ("Williamsburg", "Brooklyn"),
    "11207": ("Bushwick", "Brooklyn"), "11221": ("Bushwick", "Brooklyn"), "11237": ("Bushwick", "Brooklyn"),
    "11222": ("Greenpoint", "Brooklyn"),
    "11215": ("Park Slope & Gowanus", "Brooklyn"),
    "11217": ("Fort Greene & Boerum Hill", "Brooklyn"), "11238": ("Prospect Heights", "Brooklyn"),
    "11216": ("Bed-Stuy", "Brooklyn"), "11233": ("Bed-Stuy", "Brooklyn"),
    "11225": ("Flatbush", "Brooklyn"), "11226": ("Flatbush", "Brooklyn"), "11210": ("Flatbush", "Brooklyn"),
    "11231": ("Red Hook", "Brooklyn"), "11219": ("Borough Park", "Brooklyn"),
    # Queens
    "11385": ("Ridgewood", "Queens"), "11101": ("Long Island City", "Queens"),
    "11354": ("Flushing", "Queens"), "11367": ("Flushing", "Queens"), "11368": ("Flushing", "Queens"),
    "11373": ("Elmhurst", "Queens"), "11375": ("Forest Hills", "Queens"), "11378": ("Maspeth", "Queens"),
    # Bronx, Staten Island
    "10467": ("Bronx", "Bronx"), "10468": ("Bronx", "Bronx"),
    "10301": ("St. George", "Staten Island"),
}

OVERRIDES = {
    "Miller Theatre": "Morningside Heights",
    "Manhattan School of Music": "Morningside Heights",
    "The Riverside Church": "Morningside Heights",
    "Cathedral of St. John the Divine": "Morningside Heights",
    "Prospect Park Bandshell": "Park Slope & Gowanus",
}

BOROUGH_BY_PREFIX = {"100": "Manhattan", "101": "Manhattan", "102": "Manhattan", "103": "Staten Island",
                     "104": "Bronx", "112": "Brooklyn", "111": "Queens", "113": "Queens", "114": "Queens",
                     "116": "Queens"}


def zip_of(address: str | None) -> str | None:
    m = re.findall(r"\b(1\d{4})\b", address or "")
    return m[-1] if m else None


def area_of(name: str, address: str | None) -> tuple[str | None, str | None]:
    """(neighborhood, borough) for a venue, or (None, borough-or-None) when the ZIP isn't mapped."""
    z = zip_of(address)
    hood, borough = ZIPS.get(z, (None, BOROUGH_BY_PREFIX.get((z or "")[:3])))
    if not borough:
        a = (address or "").lower()
        borough = next((b for b in ("Brooklyn", "Queens", "Bronx", "Staten Island") if b.lower() in a), None)
        if not borough and "new york, ny" in a:
            borough = "Manhattan"
    return OVERRIDES.get(name, hood), borough

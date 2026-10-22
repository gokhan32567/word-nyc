"""Is a calendar entry a show, and is it at this venue?

Venue calendars (especially churches, schools and museums) list services, classes, tours and
meetings alongside concerts. Structured feeds don't say which is which, so titles are checked here.
"""
from __future__ import annotations

import re

# Never a show, whatever else the title says.
HARD = re.compile(
    r"\b(worship|eucharist|liturgy|prayers?|sermon|bible|scripture|sunday school|catechism|baptisms?|"
    r"funerals?|weddings?|nursery|childcare|coffee hour|fellowship|book (club|study|group)|stud(y|ies)|"
    r"class(es)?|courses?|lessons?\b(?!\s+(and|&)\s+carols)|workshops?|seminars?|lectures?|webinars?|"
    r"info(rmation)? sessions?|open house|orientation|registration|meetings?|volunteers?|service project|"
    r"care packages?|support group|yoga|meditation|tai chi|fitness|pottery|ceramics|carving|crafts?|trivia|"
    r"bingo|karaoke|brunch|screenings?|on screen|movie night|rehearsals?|auditions?|office hours|formation|parking|"
    r"guided tours?|walking tours?|house tours?|building tours?|garden tours?|historical tours?|history tours?|"
    r"heritage tours?|museum tours?|campus tours?|tours? of|private event|"
    r"closed to the public|members only)\b", re.I)

# Usually not a show unless the title also names a performance.
SOFT = re.compile(r"\b(mass|masses|services?|talks?|panels?|exhibitions?|markets?|forums?|retreats?|"
                  r"receptions?|gala|dinner|vigil|conversations?|readings?)\b", re.I)

# Words that mark a performance.
SHOW = re.compile(
    r"\b(concerts?|recitals?|performances?|performs?|performing|premieres?|festival|operas?|ballets?|dance|"
    r"cabaret|jazz|blues|orchestras?|orchestral|symphon\w*|philharmonic|sinfonia|chamber music|quartets?|"
    r"quintets?|sextets?|octets?|trios?|duos?|ensembles?|chorale|chorus|choral|oratorio|requiem|messiah|"
    r"cantatas?|vespers|evensong|passion|magnificat|stabat mater|carols|hymn festival|sing-?along|organ|"
    r"carillon|piano|pianist|violin|violinist|cello|cellist|guitar|songs?|sings?|singers?|band|dj|showcase|"
    r"variety show|comedy|stand-?up|musical|tribute|album release|open mic|jam session|live music|"
    r"in concert|bach|handel|mozart|beethoven|brahms|schubert|vivaldi|haydn|chopin|debussy|ravel|mahler|"
    r"musicevent|danceevent|theaterevent|comedyevent)\b", re.I)

# Multi-purpose places whose calendars are mostly not performances: an entry needs a performance word.
STRICT_VENUE = re.compile(r"church|cathedral|chapel|synagogue|temple|parish|abbey|basilica|holy|school|"
                          r"universit|college|conservatory|juilliard|institute|museum|library|armory|"
                          r"americas society|asia society|japan society|community|cultural cent|ymca|92ny|greenwich house", re.I)


def is_strict(venue: dict) -> bool:
    return bool(venue.get("strict", STRICT_VENUE.search(venue.get("name", ""))))


def is_show(title: str | None, hint: str = "", strict: bool = False) -> bool:
    """hint: the feed's own categories or event type (e.g. 'Concerts', 'MusicEvent')."""
    t = title or ""
    if HARD.search(t):
        return False
    strong = bool(SHOW.search(t) or SHOW.search(hint or ""))
    if SOFT.search(t) and not strong:
        return False
    return strong or not strict


# ---------------------------------------------------------------- same place?

PLACE_NOISE = re.compile(r"\b(the|nyc|new york|ny|brooklyn|manhattan|queens|bronx|at|and|of|club|bar|hall|"
                         r"theat(?:er|re)|music|room|lounge|cafe|café|venue|presents|inc|llc)\b")
STREET_WORDS = {"avenue": "ave", "av": "ave", "street": "st", "boulevard": "blvd", "place": "pl", "road": "rd",
                "first": "1st", "second": "2nd", "third": "3rd", "fourth": "4th", "fifth": "5th", "sixth": "6th",
                "seventh": "7th", "eighth": "8th", "ninth": "9th", "tenth": "10th", "eleventh": "11th",
                "twelfth": "12th"}
NY_STATES = {"ny", "new york", "n.y."}


def place_key(name: str | None) -> str:
    s = PLACE_NOISE.sub(" ", (name or "").lower())
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", s).split())


def street_key(address: str | None) -> tuple[str, str] | None:
    words = [STREET_WORDS.get(w, w) for w in re.findall(r"[a-z0-9]+", (address or "").lower())]
    for i, w in enumerate(words):
        if re.fullmatch(r"\d+[a-z]?", w):
            rest = [x for x in words[i + 1:i + 4] if x not in ("w", "e", "n", "s", "west", "east", "north", "south")]
            if rest:
                return w, rest[0]
    return None


def same_place(venue: dict, name: str | None, address: str | None, region: str | None = None) -> bool | None:
    """True if a listing's location is this venue, False if it's clearly elsewhere, None if it doesn't say."""
    if region and region.strip().lower() not in NY_STATES:
        return False
    known = False
    a, b = place_key(venue.get("name")), place_key(name)
    if a and b:
        known = True
        if a in b or b in a:
            return True
    sa, sb = street_key(venue.get("address")), street_key(address)
    if sa and sb:
        known = True
        if sa == sb:
            return True
    return False if known else None

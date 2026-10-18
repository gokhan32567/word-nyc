"""Map raw genre labels from any source onto the site's genre buckets."""
import re

# Order matters: the first bucket with a matching pattern wins.
# Patterns are regular expressions matched case-insensitively against each raw label.
BUCKETS = [
    ("Opera", [r"\bopera", r"operetta", r"zarzuela"]),
    ("Ballet & Dance", [r"ballet", r"choreograph", r"modern dance", r"contemporary dance", r"dance compan",
                        r"dance thea", r"tap dance", r"^dance$", r"^performance art/dance$"]),
    ("Comedy", [r"comedy", r"comedian", r"stand-?up"]),
    ("Avant-garde", [r"avant", r"experimental", r"new music", r"contemporary classical", r"improvis",
                     r"\bimprov\b", r"\bnoise\b", r"free jazz", r"sound art", r"electroacoustic",
                     r"minimalis", r"\bdrone\b"]),
    ("Classical", [r"classical", r"orchestra", r"symphon", r"philharmon", r"chamber", r"choral", r"\bchoir",
                   r"baroque", r"string quartet", r"\brecital", r"early music", r"\bconcerto"]),
    ("Jazz", [r"jazz", r"bebop", r"\bswing\b", r"big band", r"bossa"]),
    ("Blues", [r"blues"]),
    ("Gospel", [r"gospel", r"spiritual", r"christian", r"worship"]),
    ("R&B & Soul", [r"r&b", r"\brnb\b", r"\bsoul\b", r"\bfunk", r"motown", r"neo-soul"]),
    ("Hip-Hop & Rap", [r"hip-?hop", r"hip hop", r"\brap\b", r"\btrap\b", r"\bdrill\b", r"\bgrime\b"]),
    ("Reggae & Caribbean", [r"reggae", r"dancehall", r"\bsoca\b", r"calypso", r"\bska\b", r"\bdub\b",
                            r"caribbean", r"kompa", r"\bzouk\b"]),
    ("Latin", [r"latin", r"salsa", r"reggaeton", r"bachata", r"cumbia", r"merengue", r"\btango", r"flamenco",
               r"\bmpb\b", r"samba", r"brazil", r"afro-?cuban", r"mariachi", r"bolero", r"regional mexican",
               r"\bbanda\b", r"corrido"]),
    ("African", [r"afro", r"african", r"highlife", r"amapiano", r"soukous", r"mbalax", r"gnawa"]),
    ("Electronic & DJ", [r"electronic", r"\bedm\b", r"\bhouse\b", r"techno", r"\bdj", r"drum ?(and|&|n) ?bass",
                         r"dubstep", r"trance", r"disco", r"dance music", r"\brave\b", r"ambient", r"club night"]),
    ("Metal", [r"metal"]),
    ("Punk & Hardcore", [r"punk", r"hardcore", r"\bemo\b", r"screamo"]),
    ("Indie & Alternative", [r"indie", r"alternative", r"\balt\b", r"alt-", r"shoegaze", r"dream ?pop", r"lo-?fi"]),
    ("Rock", [r"\brock", r"psych", r"garage", r"grunge", r"rockabilly", r"surf"]),
    ("Country", [r"country", r"honky", r"western", r"nashville"]),
    ("Folk & Americana", [r"folk", r"americana", r"bluegrass", r"singer[ -/]?songwriter", r"acoustic", r"\broots\b"]),
    ("Pop", [r"\bpop\b", r"k-?pop", r"j-?pop", r"c-?pop", r"top 40"]),
    ("World", [r"world", r"balkan", r"klezmer", r"celtic", r"irish", r"indian", r"bollywood", r"arabic",
               r"middle east", r"persian", r"turkish", r"greek", r"asian", r"chinese", r"japanese", r"korean",
               r"traditional", r"global"]),
    ("Cabaret & Musicals", [r"cabaret", r"burlesque", r"musical", r"broadway", r"show ?tunes", r"\bdrag\b",
                            r"variety", r"vaudeville", r"piano bar"]),
]

GENRES = [name for name, _ in BUCKETS] + ["Other"]

# Labels that carry no information (Ticketmaster uses these a lot).
VAGUE = {"", "undefined", "other", "music", "miscellaneous", "misc", "none", "arts & theatre"}

_COMPILED = [(name, [re.compile(p, re.I) for p in pats]) for name, pats in BUCKETS]


def bucket(*labels: str) -> str:
    """Return the first bucket matching any of the given raw labels, in order of preference."""
    for raw in labels:
        text = (raw or "").strip()
        if text.lower() in VAGUE:
            continue
        for name, pats in _COMPILED:
            if any(p.search(text) for p in pats):
                return name
    return "Other"

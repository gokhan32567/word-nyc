"""Regression tests for the venue reader's checks: every case here was a real mistake once.

  python tests/test_reader.py
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scraper"))
import ai  # noqa: E402
from browse import Snapshot  # noqa: E402

NIGHT = date(2026, 10, 31)


def check(page_text, **raw):
    snap = Snapshot(venue="V", url="https://v.example/", final_url="https://v.example/", text=page_text)
    venue = {"name": raw.pop("venue_name", "Test Venue"), "lat": 40.7, "lng": -74.0, "genre": "Jazz", **raw.pop("venue", {})}
    base = {"public_performance": True, "at_this_venue": True, "venue_shown": ""}
    return ai.check({**base, **raw}, snap, [], NIGHT, venue, ai._squash(page_text), ai.norm(page_text))


def test_bar_bayeux_two_sets():  # "SAT 8 & 9:30" is an 8 PM and a 9:30 PM set
    assert ai.times_in("SAT 8 & 9:30 - Theo Bleckmann") == {20 * 60, 21 * 60 + 30}


def test_title_prefix_removed():
    assert ai.DAY_TIMES_PREFIX.sub("", "SAT 8 & 9:30 - Theo Bleckmann Trio") == "Theo Bleckmann Trio"
    assert ai.DAY_TIMES_PREFIX.sub("", "Sun Ra Arkestra") == "Sun Ra Arkestra"


def test_final_check_needs_proof():  # Ron Carter was "cancelled" with a quote that said nothing of the kind
    v = {"name": "Birdland"}
    assert not ai.proves("cancelled_or_postponed", "RON CARTER QUARTET SAT OCT 31 Doors @ 7:30PM", NIGHT, v)
    assert ai.proves("cancelled_or_postponed", "CANCELLED - Ron Carter", NIGHT, v)
    assert not ai.proves("other_night", "SAT OCT 31 Doors 7:30PM", NIGHT, v)


def test_closed_tonight():
    assert ai.CLOSED.search("HALLOWEEN – CLOSED FOR THE HOLIDAY")
    assert not ai.CLOSED.search("Closing Night Party")


def test_oct_31_beside_title():  # Jazz Gallery / Club Cumming: "OCT" over "31" over the title
    page = "OCT\n31\nDabin Ryu Discomfort Album Release Concert\nSets at 7pm + 9pm ET"
    ev, why = check(page, title="Dabin Ryu Discomfort Album Release Concert", start_time="7:00 PM",
                    date_evidence="31", time_evidence="Sets at 7pm + 9pm ET")
    assert ev and ev["time"] == "7:00 PM", why


def test_grid_cell_must_be_tonights():  # Blue Note grid: the show must sit in day 31's own cell
    page = "OCTOBER 2026\n30\nOther Band\n8:00 PM\n31\nRobert Glasper Halloween\n8:00 PM & 10:30 PM\n"
    ok, why = check(page, title="Robert Glasper Halloween", start_time="8:00 PM", date_evidence="31",
                    time_evidence="8:00 PM & 10:30 PM")
    assert ok, why
    wrong, _ = check(page, title="Other Band", start_time="8:00 PM", date_evidence="31", time_evidence="8:00 PM")
    assert wrong is None


def test_event_page_for_tomorrow_rejected():  # Zinc Bar: tomorrow's show at "12:00 AM" is not a late set
    page = "VALTINHO ANASTÁCIO\nNovember 1, 2026 12:00 am"
    ev, why = check(page, title="VALTINHO ANASTÁCIO", start_time="12:00 AM", date_evidence="November 1, 2026",
                    time_evidence="12:00 am", venue={"no_follow": True})
    assert ev is None, why


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print("ok  ", name)
            except AssertionError as e:
                fails += 1
                print("FAIL", name, e)
    sys.exit(1 if fails else 0)

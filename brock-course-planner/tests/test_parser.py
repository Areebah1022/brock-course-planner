from pathlib import Path

import pytest

from planner.parser import (
    credit_weight,
    extract_codes,
    parse_calendar_html,
    parse_requirement,
    replace_halves,
)
from tests.fixture import FIXTURE_HTML


@pytest.fixture(scope="module")
def cal():
    return parse_calendar_html(FIXTURE_HTML)


def C(code, min_grade=None):
    return {"type": "course", "code": code, "min_grade": min_grade}


# ---- small helpers -----------------------------------------------------------------

def test_credit_weight_from_code():
    assert credit_weight("COSC 2P03") == 0.5
    assert credit_weight("COSC 4F90") == 1.0
    assert credit_weight("COSC 0N01") == 0.0


def test_replace_halves():
    assert replace_halves("three and one-half COSC credits") == "3.5 COSC credits"
    assert replace_halves("one-half elective") == "0.5 elective"


def test_extract_codes_inherits_subject():
    assert extract_codes("COSC 2P90 and 3P05") == ["COSC 2P90", "COSC 3P05"]


# ---- page-level parsing ------------------------------------------------------------

def test_metadata(cal):
    assert cal["calendar_year"] == "2099-2100"
    assert len(cal["courses"]) == 10


def test_basic_fields(cal):
    c = cal["courses"]["TEST 2P01"]
    assert c["title"] == "Advanced Widgets"
    assert c["description"] == "Build bigger widgets."
    assert c["format"].startswith("Lectures, 3 hours")
    assert c["restriction"] == "open to TEST (single or combined) majors."
    assert c["notes"][0] == "offered in the fall."
    assert c["replaces"] == ["TEST 2P90", "TEST 3P05"]
    assert c["cross_list_marker"] == "secondary"


def test_cross_listing_as_own_paragraph_is_not_the_description(cal):
    c = cal["courses"]["TEST 2P01"]
    assert c["cross_listed"] == ["ALSO 2P01"]
    assert "also offered" not in c["description"]


def test_cross_listing_inside_title(cal):
    c = cal["courses"]["TEST 3P01"]
    assert c["title"] == "Widget Algorithms"
    assert c["cross_listed"] == ["ALSO 3P01"]


def test_course_without_prereq(cal):
    assert cal["courses"]["TEST 1P01"]["prerequisites"] is None


def test_restriction_mislabelled_as_prerequisite(cal):
    c = cal["courses"]["TEST 4P01"]
    assert c["restriction"] is None
    assert c["prerequisites"]["expr"] == C("TEST 3P01", 70)
    assert c["data_quality_notes"]


def test_corequisite(cal):
    c = cal["courses"]["TEST 4P02"]
    assert c["corequisites"]["expr"] == C("TEST 0N01")
    assert c["prerequisites"]["expr"] == C("SCIE 0N90")


def test_footer_paragraph_not_treated_as_course_content(cal):
    # 'Last updated' is just the final <p> here, so it lands in notes rather than crashing.
    assert cal["courses"]["TEST 4P02"]["description"] == "Work with widgets."


# ---- requirement grammar -----------------------------------------------------------

def test_comma_and_bare_codes_inherit_subject(cal):
    expr = cal["courses"]["TEST 2P01"]["prerequisites"]["expr"]
    assert expr == {"op": "and", "args": [C("TEST 1P01", 60), C("MATH 1P66"), C("MATH 1P67")]}


def test_and_binds_tighter_than_or(cal):
    p = cal["courses"]["TEST 3P01"]["prerequisites"]
    assert p["parsed"]
    assert p["expr"] == {"op": "or", "args": [
        {"op": "and", "args": [C("TEST 1P01", 60), C("TEST 1P02", 60)]},
        C("TEST 2P01", 70),
    ]}


def test_one_of(cal):
    expr = cal["courses"]["TEST 3P02"]["prerequisites"]["expr"]
    assert expr == {"op": "or", "args": [C("TEST 1P01"), C("TEST 2P01"), C("MATH 2P40")]}


def test_half_credits_and_permission(cal):
    expr = cal["courses"]["TEST 3P03"]["prerequisites"]["expr"]
    assert expr["args"][0] == {"type": "credits", "subject": "TEST", "n": 3.5, "min_grade": None}
    assert expr["args"][1]["type"] == "permission"


def test_credits_from_options(cal):
    expr = cal["courses"]["TEST 3P04"]["prerequisites"]["expr"]
    assert expr["type"] == "credits_from" and expr["n"] == 2
    assert [o["subject"] for o in expr["options"]] == ["TEST", "MATH", "STAT"]
    assert all(o["min_grade"] == 60 for o in expr["options"])


def test_unknown_phrase_is_kept_and_flagged(cal):
    p = cal["courses"]["TEST 3P05"]["prerequisites"]
    assert p["parsed"] is False
    assert p["expr"]["args"][0] == C("TEST 1P01")  # the part we DO understand survives
    assert p["expr"]["args"][1] == {"type": "other", "text": "4U Mathematics credit"}


def test_major_specific_requirements_are_not_guessed(cal):
    p = cal["courses"]["TEST 3P06"]["prerequisites"]
    assert p["parsed"] is False
    assert p["expr"]["type"] == "other"


def test_empty_requirement():
    assert parse_requirement("Prerequisite(s): ") is None


# ---- the real calendar (only runs if you've saved it locally; it's git-ignored) ----

REAL = Path(__file__).resolve().parent.parent / "data" / "raw" / "cosc_2024.html"


@pytest.mark.skipif(not REAL.exists(), reason="real calendar page not saved locally")
def test_real_calendar_known_facts():
    cal = parse_calendar_html(REAL.read_text(encoding="utf-8", errors="replace"))
    courses = cal["courses"]
    assert cal["calendar_year"] == "2024-2025"
    assert len(courses) == 69

    p = courses["COSC 2P03"]["prerequisites"]["expr"]
    assert p == {"op": "and", "args": [C("COSC 1P03", 60), C("MATH 1P66"), C("MATH 1P67")]}

    # Cross-listed courses must have a real description, not the "(also offered as ...)" line.
    assert courses["COSC 2P08"]["cross_listed"] == ["DASA 2P08"]
    assert courses["COSC 2P08"]["description"].startswith("Introduction to Python")

    # Every course has a title and a description.
    assert all(c["title"] and c["description"] for c in courses.values())

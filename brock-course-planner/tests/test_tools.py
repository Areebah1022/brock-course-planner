import pytest

from planner.parser import parse_calendar_html
from planner.tools import MET, NOT_MET, UNKNOWN, Catalog, normalize_code
from tests.fixture import FIXTURE_HTML


@pytest.fixture(scope="module")
def catalog():
    return Catalog(parse_calendar_html(FIXTURE_HTML))


def test_normalize_code():
    assert normalize_code("test2p01") == "TEST 2P01"
    assert normalize_code("  Test  2p01 ") == "TEST 2P01"


def test_get_course_is_forgiving(catalog):
    assert catalog.get_course("test 2p01")["title"] == "Advanced Widgets"
    assert catalog.get_course("NOPE 1P01") is None


def test_met(catalog):
    done = {"TEST 1P01": 75, "MATH 1P66": 70, "MATH 1P67": 65}
    assert catalog.check_prereqs("TEST 2P01", done)["status"] == MET


def test_grade_below_minimum(catalog):
    done = {"TEST 1P01": 55, "MATH 1P66": 70, "MATH 1P67": 65}
    r = catalog.check_prereqs("TEST 2P01", done)
    assert r["status"] == NOT_MET
    assert "55%" in r["reasons"][0]


def test_missing_course(catalog):
    r = catalog.check_prereqs("TEST 2P01", {"TEST 1P01": 75})
    assert r["status"] == NOT_MET
    assert any("MATH 1P66" in reason for reason in r["reasons"])


def test_missing_grade_is_unknown_not_failure(catalog):
    done = {"TEST 1P01": None, "MATH 1P66": 70, "MATH 1P67": 65}
    assert catalog.check_prereqs("TEST 2P01", done)["status"] == UNKNOWN


def test_or_branch_either_side_works(catalog):
    via_and = {"TEST 1P01": 70, "TEST 1P02": 70}
    via_or = {"TEST 2P01": 80}
    neither = {"TEST 1P01": 70}
    assert catalog.check_prereqs("TEST 3P01", via_and)["status"] == MET
    assert catalog.check_prereqs("TEST 3P01", via_or)["status"] == MET
    assert catalog.check_prereqs("TEST 3P01", neither)["status"] == NOT_MET


def test_one_of(catalog):
    assert catalog.check_prereqs("TEST 3P02", {"MATH 2P40": 50})["status"] == MET
    assert catalog.check_prereqs("TEST 3P02", {})["status"] == NOT_MET


def test_credit_counting_uses_code_weights(catalog):
    # 3P04 needs 2 credits from TEST/MATH/STAT at 60%. Two full-credit (F) courses = 2.0.
    assert catalog.check_prereqs("TEST 3P04", {"TEST 1F01": 70, "MATH 1F01": 70})["status"] == MET
    # Four half-credit (P) courses = 2.0, but one is below 60%, so only 1.5 counts.
    done = {"TEST 1P01": 70, "TEST 1P02": 70, "MATH 1P01": 70, "STAT 1P01": 50}
    r = catalog.check_prereqs("TEST 3P04", done)
    assert r["status"] == NOT_MET and "1.5" in r["reasons"][0]


def test_credits_from_unknown_grades(catalog):
    # 1.5 credits are certain; the 4th half-credit course has no grade, so it MIGHT make 2.0.
    done = {"TEST 1P01": 70, "TEST 1P02": 70, "TEST 1P03": 70, "MATH 1P01": None}
    assert catalog.check_prereqs("TEST 3P04", done)["status"] == UNKNOWN
    # Even if that grade turned out fine, 1.0 + 0.5 can never reach 2.0.
    assert catalog.check_prereqs("TEST 3P04", {"TEST 1P01": 70, "MATH 1P01": None})["status"] == NOT_MET


def test_permission_is_unknown(catalog):
    done = {f"TEST {n}": 70 for n in ("1P01", "1P02", "1P03", "1P04", "1P05", "1P06", "1P07")}
    r = catalog.check_prereqs("TEST 3P03", done)
    assert r["status"] == UNKNOWN
    assert any("permission" in reason for reason in r["reasons"])


def test_uninterpretable_requirement_never_claims_met(catalog):
    # TEST 1P01 satisfies the OR... but 'or' with an unknown still resolves to MET if one side is met.
    assert catalog.check_prereqs("TEST 3P05", {"TEST 1P01": 70})["status"] == MET
    # Without it, we must say "unknown", not "not met": the 4U credit might satisfy it.
    r = catalog.check_prereqs("TEST 3P05", {})
    assert r["status"] == UNKNOWN
    assert any("advisor" in reason for reason in r["reasons"])


def test_major_specific_requirement_is_unknown(catalog):
    assert catalog.check_prereqs("TEST 3P06", {"TEST 1P01": 90})["status"] == UNKNOWN


def test_unknown_course(catalog):
    r = catalog.check_prereqs("NOPE 9P99", {})
    assert r["status"] == UNKNOWN


def test_corequisite_and_restriction_surface_as_notes(catalog):
    r = catalog.check_prereqs("TEST 4P02", {"SCIE 0N90": None})
    assert any("TEST 0N01" in n for n in r["notes"])
    r2 = catalog.check_prereqs("TEST 2P01", {})
    assert any("Restriction" in n for n in r2["notes"])


def test_available_courses_skips_completed_and_failures(catalog):
    done = {"TEST 1P01": 70}
    codes = {r["code"] for r in catalog.available_courses(done)}
    assert "TEST 1P01" not in codes     # already done
    assert "TEST 3P02" in codes         # satisfied by TEST 1P01
    assert "TEST 2P01" not in codes     # missing MATH prerequisites


def test_search(catalog):
    assert [c["code"] for c in catalog.search("sort widgets")] == ["TEST 3P01"]

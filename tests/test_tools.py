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


def test_corequisite_surfaces_as_note_and_restriction_text_is_kept(catalog):
    r = catalog.check_prereqs("TEST 4P02", {"SCIE 0N90": None})
    assert any("TEST 0N01" in n for n in r["notes"])
    r2 = catalog.check_prereqs("TEST 2P01", {})
    assert r2["restriction"]["text"] == "open to TEST (single or combined) majors."


def test_available_courses_skips_completed_and_failures(catalog):
    done = {"TEST 1P01": 70}
    codes = {r["code"] for r in catalog.available_courses(done)}
    assert "TEST 1P01" not in codes     # already done
    assert "TEST 3P02" in codes         # satisfied by TEST 1P01
    assert "TEST 2P01" not in codes     # missing MATH prerequisites


def test_search(catalog):
    assert [c["code"] for c in catalog.search("sort widgets")] == ["TEST 3P01"]


# ---- restrictions: who may enrol ---------------------------------------------------------

from planner.parser import parse_restriction
from planner.tools import (ALLOWED, CHECK_REQUIRED, CONDITIONAL, ELIGIBLE, NOT_ALLOWED, NOT_ELIGIBLE,
                           RESTR_UNKNOWN, check_restriction, overall_verdict)

COSC_COOP = {"program": "COSC", "coop": True, "minors": []}


def verdict(text, profile):
    return check_restriction(parse_restriction(text), profile)["status"]


def test_no_restriction_means_allowed():
    assert check_restriction(None, COSC_COOP)["status"] == ALLOWED


def test_restriction_unknown_until_program_is_set():
    assert verdict("open to COSC majors.", {}) == RESTR_UNKNOWN


def test_open_to_list():
    assert verdict("open to COSC (single or combined), BCB and CAST majors.", COSC_COOP) == ALLOWED
    assert verdict("open to GAMP majors.", COSC_COOP) == NOT_ALLOWED


def test_not_open_to_list():
    text = "not open to COSC (single or combined), BCB and CAST majors."
    assert verdict(text, COSC_COOP) == NOT_ALLOWED
    assert verdict(text, {"program": "VISA", "coop": False}) == ALLOWED


def test_exclusion_wins_even_if_date_limited_open_list_exists():
    text = "open to IASC majors until date specified in Registration guide. Not open to COSC majors."
    assert verdict(text, COSC_COOP) == NOT_ALLOWED


def test_coop_only():
    text = "open to COSC and BCB Co-op students."
    assert verdict(text, COSC_COOP) == ALLOWED
    assert verdict(text, {"program": "COSC", "coop": False}) == NOT_ALLOWED
    assert verdict(text, {"program": "COSC", "coop": None}) == RESTR_UNKNOWN
    assert verdict(text, {"program": "VISA", "coop": True}) == NOT_ALLOWED


def test_conditions_make_it_conditional_not_allowed():
    text = ("open to COSC majors with a minimum 75 percent major average "
            "and permission of project co-ordinator.")
    r = check_restriction(parse_restriction(text), COSC_COOP)
    assert r["status"] == CONDITIONAL
    assert any("75%" in reason for reason in r["reasons"])
    assert any("permission of project co-ordinator" in reason for reason in r["reasons"])


def test_minors():
    text = "open to APCO minors."
    assert verdict(text, COSC_COOP) == NOT_ALLOWED
    assert verdict(text, {"program": "COSC", "minors": ["APCO"]}) == ALLOWED


def test_date_limited_with_later_list():
    text = ("open to STAC majors until date specified in Registration guide. "
            "After that date open to STAC majors and APCO minors.")
    assert verdict(text, COSC_COOP) == NOT_ALLOWED
    assert verdict(text, {"program": "COSC", "minors": ["APCO"]}) == CONDITIONAL
    assert verdict(text, {"program": "STAC"}) == ALLOWED


def test_date_limited_without_later_list_is_not_a_flat_no():
    assert verdict("open to APCO minors until date specified in Registration guide.", COSC_COOP) == CONDITIONAL


def test_unrecognised_restriction_is_unknown_not_guessed():
    assert verdict("see the department chair.", COSC_COOP) == RESTR_UNKNOWN


def test_overall_verdict_combines_both():
    assert overall_verdict("met", "allowed") == ELIGIBLE
    assert overall_verdict("not_met", "allowed") == NOT_ELIGIBLE
    assert overall_verdict("met", "not_allowed") == NOT_ELIGIBLE
    assert overall_verdict("unknown", "allowed") == CHECK_REQUIRED
    assert overall_verdict("met", "conditional") == CHECK_REQUIRED


def test_check_prereqs_applies_program(catalog):
    done = {"TEST 1P01": 75, "MATH 1P66": 70, "MATH 1P67": 65}  # satisfies TEST 2P01's prerequisites
    mine = catalog.check_prereqs("TEST 2P01", done, {"program": "TEST", "coop": False})
    other = catalog.check_prereqs("TEST 2P01", done, {"program": "ARTS", "coop": False})
    assert mine["overall"] == ELIGIBLE
    assert other["overall"] == NOT_ELIGIBLE and other["status"] == "met"  # prereqs fine, program isn't


def test_available_courses_hides_courses_the_program_cannot_take(catalog):
    done = {"TEST 1P01": 75, "MATH 1P66": 70, "MATH 1P67": 65}
    mine = {r["code"] for r in catalog.available_courses(done, profile={"program": "TEST", "coop": False})}
    other = {r["code"] for r in catalog.available_courses(done, profile={"program": "ARTS", "coop": False})}
    assert "TEST 2P01" in mine and "TEST 2P01" not in other


def test_cross_listed_duplicates_shown_once_preferring_students_program():
    def course(code, other):
        subject, number = code.split()
        return {"code": code, "subject": subject, "number": number, "credits": 0.5, "title": "Shared",
                "description": "", "format": None, "prerequisites": None, "corequisites": None,
                "restriction": None, "restriction_rule": None, "notes": [], "replaces": [],
                "cross_listed": [other], "cross_list_marker": None, "data_quality_notes": []}

    cat = Catalog({"calendar_year": "x", "courses": {
        "APCO 1P50": course("APCO 1P50", "COSC 1P50"), "COSC 1P50": course("COSC 1P50", "APCO 1P50")}})
    codes = [r["code"] for r in cat.available_courses({}, profile={"program": "COSC"})]
    assert codes == ["COSC 1P50"]


def test_special_topics_course_is_never_marked_eligible():
    topics = {"code": "TEST 3V90-3V99", "subject": "TEST", "number": "3V90-3V99", "credits": 0.5,
              "title": "Topics", "description": "Selected topics.", "format": None,
              "prerequisites": None, "corequisites": None, "restriction": None,
              "restriction_rule": None, "notes": [], "replaces": [], "cross_listed": [],
              "cross_list_marker": None, "data_quality_notes": []}
    r = Catalog({"calendar_year": "x", "courses": {topics["code"]: topics}}).check_prereqs(
        "TEST 3V90-3V99", {}, {"program": "TEST", "coop": False})
    assert r["status"] == "unknown" and r["overall"] == CHECK_REQUIRED
    assert "specific topic" in r["reasons"][0]

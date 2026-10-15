"""Deterministic tools the planning agent can call.

Everything here is plain Python. The model decides WHICH tool to call and explains the
results, but the actual prerequisite logic lives in code so it is testable and never
"hallucinated".

`completed` is a dict of the student's finished courses: {"COSC 1P03": 82, "MATH 1P66": None}
where the value is the final percentage, or None if the student did not say.
"""

import json
import re
from pathlib import Path

from planner.parser import credit_weight

MET, NOT_MET, UNKNOWN = "met", "not_met", "unknown"

# Restriction ("who may enrol") statuses
ALLOWED, NOT_ALLOWED, CONDITIONAL, RESTR_UNKNOWN = "allowed", "not_allowed", "conditional", "unknown"
# Overall verdict combining prerequisites + restriction
ELIGIBLE, NOT_ELIGIBLE, CHECK_REQUIRED = "eligible", "not_eligible", "check_required"

DEFAULT_DATA = Path(__file__).resolve().parent.parent / "data" / "courses.json"



# --------------------------------------------------------------------------- restrictions

def check_restriction(rule, profile):
    """Apply a parsed restriction rule to a student profile.

    profile: {"program": "COSC", "coop": True/False/None, "minors": ["APCO"]}  ({} = not set yet)
    Returns {"status": allowed | not_allowed | conditional | unknown, "reasons": [...]}.
    """
    if not rule:
        return {"status": ALLOWED, "reasons": []}

    program = (profile or {}).get("program")
    if not program:
        return {"status": RESTR_UNKNOWN,
                "reasons": [f"Restriction: \"{rule['raw']}\". Student's program isn't set yet."]}
    if not rule["parsed"]:
        return {"status": RESTR_UNKNOWN,
                "reasons": [f"Could not interpret restriction automatically: \"{rule['raw']}\"."]}

    coop = profile.get("coop")
    minors = set(profile.get("minors") or [])

    if program in rule["not_open_to"]:
        return {"status": NOT_ALLOWED, "reasons": [f"Not open to {program} students."]}

    has_open_list = bool(rule["open_to"] or rule["minors"])
    if not has_open_list:
        # Only an exclusion list, and the student isn't on it.
        return {"status": ALLOWED, "reasons": []}

    reasons = []
    in_list = program in rule["open_to"] or bool(minors & set(rule["minors"]))
    if in_list:
        if rule["coop_only"]:
            if coop is False:
                return {"status": NOT_ALLOWED, "reasons": ["Open only to Co-op students."]}
            if coop is None:
                return {"status": RESTR_UNKNOWN, "reasons": ["Open only to Co-op students; Co-op status not set."]}
        if rule["conditions"]:
            return {"status": CONDITIONAL,
                    "reasons": [f"Requires: {c}." for c in rule["conditions"]]}
        return {"status": ALLOWED, "reasons": []}

    # Not on the "open now" list.
    if rule["later_open_to"] or rule["later_minors"]:
        later = program in rule["later_open_to"] or bool(minors & set(rule["later_minors"]))
        if later:
            return {"status": CONDITIONAL,
                    "reasons": ["Restricted to other programs until a date in the Registration guide; "
                                "then open to your program."]}
        return {"status": NOT_ALLOWED, "reasons": [f"Not open to {program} students."]}
    if rule["date_limited"]:
        return {"status": CONDITIONAL,
                "reasons": ["Restricted to other programs until a date in the Registration guide; "
                            "check whether it opens to your program afterwards."]}
    return {"status": NOT_ALLOWED, "reasons": [f"Not open to {program} students."]}


def overall_verdict(prereq_status, restriction_status):
    if prereq_status == NOT_MET or restriction_status == NOT_ALLOWED:
        return NOT_ELIGIBLE
    if prereq_status == MET and restriction_status == ALLOWED:
        return ELIGIBLE
    return CHECK_REQUIRED


# --------------------------------------------------------------------------- catalog

class Catalog:
    def __init__(self, data: dict):
        self.calendar_year = data.get("calendar_year")
        self.last_updated = data.get("last_updated")
        self.courses = data["courses"]

    @classmethod
    def load(cls, path=DEFAULT_DATA):
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def get_course(self, code: str):
        return self.courses.get(normalize_code(code))

    def search(self, keyword: str, limit: int = 10):
        """Case-insensitive search over titles and descriptions."""
        kw = keyword.lower()
        hits = [c for c in self.courses.values()
                if kw in (c["title"] or "").lower() or kw in (c["description"] or "").lower()]
        return hits[:limit]

    def check_prereqs(self, code: str, completed: dict, profile: dict | None = None) -> dict:
        """Can the student take this course? Checks prerequisites AND who may enrol.

        `status` is about prerequisites only (met / not_met / unknown).
        `restriction` is about the student's program (see check_restriction).
        `overall` combines both: eligible / not_eligible / check_required.
        """
        course = self.get_course(code)
        if course is None:
            return {"code": normalize_code(code), "status": UNKNOWN, "overall": CHECK_REQUIRED,
                    "reasons": [f"{normalize_code(code)} is not in the {self.calendar_year} calendar data."]}

        completed = {normalize_code(k): v for k, v in completed.items()}
        status, reasons = MET, []

        prereq = course["prerequisites"]
        if prereq:
            status, reasons = evaluate(prereq["expr"], completed)

        if "-" in course["code"] and status == MET:
            # Placeholder codes like COSC 3V90-3V99: the calendar lists no prerequisites because the
            # real ones depend on the specific topic offered. Don't turn "none listed" into a yes.
            status = UNKNOWN
            reasons = ["Special-topics course: prerequisites depend on the specific topic offered "
                       "that term. Confirm with the department."]

        restriction = check_restriction(course.get("restriction_rule"), profile)
        restriction["text"] = course["restriction"]

        notes = []
        coreq = course["corequisites"]
        if coreq:
            notes.append(f"Must be taken at the same time as (or after): {coreq['raw']}")
        notes.append("Not every course runs every term; check the timetable.")

        return {
            "code": course["code"],
            "title": course["title"],
            "credits": course["credits"],
            "status": status,
            "reasons": reasons,
            "restriction": restriction,
            "overall": overall_verdict(status, restriction["status"]),
            "notes": notes,
            "calendar_year": self.calendar_year,
        }

    def available_courses(self, completed: dict, subject: str | None = None,
                          profile: dict | None = None):
        """Courses the student could take: prerequisites met (or unknown) and not excluded
        by their program. Cross-listed duplicates (COSC 1P50 / APCO 1P50) are shown once."""
        done = {normalize_code(k) for k in completed}
        results = []
        for course in self.courses.values():
            if course["code"] in done or (subject and course["subject"] != subject):
                continue
            result = self.check_prereqs(course["code"], completed, profile)
            if result["overall"] != NOT_ELIGIBLE:
                result["cross_listed"] = course["cross_listed"]
                results.append(result)

        # Collapse cross-listed duplicates, preferring the student's own program's code.
        program = (profile or {}).get("program")
        kept, seen = [], {}
        for r in results:
            group = frozenset([r["code"], *r["cross_listed"]])
            overlap = next((g for g in seen if g & group), None)
            if overlap is None:
                seen[group] = len(kept)
                kept.append(r)
            elif r["code"].startswith((program or "") + " ") and program:
                kept[seen[overlap]] = r
        return kept


def normalize_code(code: str) -> str:
    """'cosc2p03' / 'cosc 2p03' / 'COSC  2P03' -> 'COSC 2P03'"""
    m = re.match(r"^\s*([A-Za-z]{3,4})\s*(\d[A-Za-z]\d{2}(?:-\d[A-Za-z]\d{2})?)\s*$", code)
    return f"{m.group(1).upper()} {m.group(2).upper()}" if m else code.strip().upper()


# --------------------------------------------------------------------------- evaluation

def _combine_and(results):
    statuses = [s for s, _ in results]
    reasons = [r for s, rs in results if s != MET for r in rs]
    if NOT_MET in statuses:
        return NOT_MET, reasons
    return (UNKNOWN if UNKNOWN in statuses else MET), reasons


def _combine_or(results):
    statuses = [s for s, _ in results]
    if MET in statuses:
        return MET, []
    reasons = [r for _, rs in results for r in rs]
    return (UNKNOWN if UNKNOWN in statuses else NOT_MET), reasons


def _course_status(code, min_grade, completed):
    if code not in completed:
        need = f" with at least {min_grade}%" if min_grade else ""
        return NOT_MET, [f"Need {code}{need}."]
    grade = completed[code]
    if min_grade is None:
        return MET, []
    if grade is None:
        return UNKNOWN, [f"{code} requires at least {min_grade}%; your grade wasn't provided."]
    if grade < min_grade:
        return NOT_MET, [f"{code} requires at least {min_grade}% (you have {grade}%)."]
    return MET, []


def _credit_totals(completed, rule_for):
    """Return (certain, possible) credit totals.

    `rule_for(code)` returns None if the course doesn't count, otherwise the minimum
    grade that course needs (or None for "no minimum").
    """
    certain = possible = 0.0
    for code, grade in completed.items():
        counts, min_grade = rule_for(code)
        if not counts:
            continue
        w = credit_weight(code)
        if min_grade is None or (grade is not None and grade >= min_grade):
            certain += w
        elif grade is None:
            possible += w
    return certain, possible


def _credits_status(n, certain, possible, label):
    if certain >= n:
        return MET, []
    if certain + possible >= n:
        return UNKNOWN, [f"Need {n:g} {label} credits at the required grade; some grades weren't provided."]
    return NOT_MET, [f"Need {n:g} {label} credits (you have {certain:g})."]


def evaluate(expr, completed):
    """Evaluate a requirement tree. Returns (status, reasons)."""
    if "op" in expr:
        results = [evaluate(a, completed) for a in expr["args"]]
        return _combine_and(results) if expr["op"] == "and" else _combine_or(results)

    kind = expr["type"]

    if kind == "course":
        return _course_status(expr["code"], expr["min_grade"], completed)

    if kind == "credits":
        subject = expr["subject"]
        certain, possible = _credit_totals(
            completed,
            lambda c: (subject is None or c.startswith(subject + " "), expr["min_grade"]))
        return _credits_status(expr["n"], certain, possible, subject or "")

    if kind == "credits_from":
        def rule_for(code):
            for o in expr["options"]:
                hit = (o["code"] == code) if o["code"] else code.startswith((o["subject"] or "") + " ")
                if hit:
                    return True, o["min_grade"]
            return False, None

        certain, possible = _credit_totals(completed, rule_for)
        label = "/".join(o["code"] or o["subject"] for o in expr["options"])
        return _credits_status(expr["n"], certain, possible, label)

    if kind == "permission":
        return UNKNOWN, [f"Requires {expr['text']}."]

    # type == "other": the parser couldn't interpret this, so a human has to check.
    return UNKNOWN, [f"Could not interpret automatically: \"{expr['text']}\". Confirm with an advisor."]

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

DEFAULT_DATA = Path(__file__).resolve().parent.parent / "data" / "courses.json"


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

    def check_prereqs(self, code: str, completed: dict) -> dict:
        """Can the student take this course given what they've completed?"""
        course = self.get_course(code)
        if course is None:
            return {"code": normalize_code(code), "status": UNKNOWN,
                    "reasons": [f"{normalize_code(code)} is not in the {self.calendar_year} calendar data."]}

        completed = {normalize_code(k): v for k, v in completed.items()}
        status, reasons = MET, []

        prereq = course["prerequisites"]
        if prereq:
            status, reasons = evaluate(prereq["expr"], completed)

        coreq = course["corequisites"]
        notes = []
        if coreq:
            notes.append(f"Must be taken at the same time as (or after): {coreq['raw']}")
        if course["restriction"]:
            notes.append(f"Restriction (verify against your program): {course['restriction']}")
        notes.append("Not every course runs every term; check the timetable.")

        return {
            "code": course["code"],
            "title": course["title"],
            "status": status,
            "reasons": reasons,
            "notes": notes,
            "calendar_year": self.calendar_year,
        }

    def available_courses(self, completed: dict, subject: str | None = None):
        """Courses the student is eligible for (or might be, if a grade/permission is unknown)."""
        done = {normalize_code(k) for k in completed}
        out = []
        for course in self.courses.values():
            if course["code"] in done or (subject and course["subject"] != subject):
                continue
            result = self.check_prereqs(course["code"], completed)
            if result["status"] in (MET, UNKNOWN):
                out.append(result)
        return out


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

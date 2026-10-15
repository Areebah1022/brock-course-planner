"""Parse a Brock University calendar page (brocku.ca/webcal/...) into structured JSON.

Each course in the page looks like this:

    <p class="calccode"><a name="COSC_2P03">COSC 2P03</a></p>
    <p class="calcname">Advanced Data Structures</p>
    <p class="calnormal">description...</p>
    <p class="calitalic">Lectures, 3 hours per week; ...</p>
    <p class="calnormal">Restriction: ...</p>
    <p class="calnormal">Prerequisite(s): COSC 1P03 (minimum 60 percent), MATH 1P66 and 1P67.</p>
    <p class="calnormal">Note: ...</p>

Prerequisites are turned into a small expression tree so code (not a language model)
can check them reliably. Anything the parser can't confidently understand is kept as an
"other" leaf and the requirement is flagged `parsed: false`, so the agent knows to ask
the student or point them to an advisor instead of guessing.

Usage:
    python -m planner.parser data/raw/cosc_2024.html -o data/courses.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

SUBJECT = r"[A-Z]{3,4}"
NUMBER = r"\d[A-Z]\d{2}"
CODE_RE = re.compile(rf"({SUBJECT})\s+({NUMBER})")

NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}

# Credit weight is encoded in the course code: 2P03 -> the letter 'P' means half a credit.
# P, F, Q, N are the standard Brock conventions. V and C are ASSUMPTIONS - verify them.
CREDIT_WEIGHTS = {"P": 0.5, "F": 1.0, "Q": 0.25, "N": 0.0, "V": 0.5, "C": 0.0}


class Unparseable(Exception):
    """Raised when a requirement is too complex for the simple grammar."""


# --------------------------------------------------------------------------- helpers

def normalize(text: str) -> str:
    """Collapse whitespace (including non-breaking spaces) to single spaces."""
    return re.sub(r"\s+", " ", text).strip()


def credit_weight(code: str) -> float:
    """'COSC 2P03' -> 0.5, 'COSC 4F90' -> 1.0. Unknown letters default to 0.5."""
    m = re.search(r"\d([A-Z])\d{2}", code)
    return CREDIT_WEIGHTS.get(m.group(1), 0.5) if m else 0.5


def parse_number(token: str) -> float:
    """'three' -> 3, '3.5' -> 3.5."""
    token = token.lower()
    if token in NUMBER_WORDS:
        return float(NUMBER_WORDS[token])
    return float(token)


def replace_halves(text: str) -> str:
    """Rewrite 'three and one-half' as '3.5' and 'one-half' as '0.5'.

    Must run BEFORE splitting on ' and ', or 'three and one-half COSC credits'
    would be torn into two pieces.
    """
    def combine(m):
        return str(NUMBER_WORDS[m.group(1).lower()] + 0.5)

    text = re.sub(r"\b(one|two|three|four|five|six) and one-half\b", combine, text, flags=re.I)
    return re.sub(r"\bone-half\b", "0.5", text, flags=re.I)


def extract_codes(text: str) -> list[str]:
    """Pull course codes out of free text, letting bare numbers inherit the last subject.

    'COSC 2P90 and 3P05' -> ['COSC 2P90', 'COSC 3P05']
    """
    codes, last_subject = [], None
    for m in re.finditer(rf"(?:({SUBJECT})\s+)?({NUMBER})", text):
        subject = m.group(1) or last_subject
        if subject:
            codes.append(f"{subject} {m.group(2)}")
            last_subject = subject
    return codes


# --------------------------------------------------------------------------- requirement grammar
#
# An expression is one of:
#   {"op": "and" | "or", "args": [expr, ...]}
#   {"type": "course",       "code": "COSC 2P03", "min_grade": 60 | None}
#   {"type": "credits",      "subject": "COSC" | None, "n": 3.5, "min_grade": None}
#   {"type": "credits_from", "n": 2, "options": [{"subject":..., "code":..., "min_grade":...}]}
#   {"type": "permission",   "text": "permission of the instructor"}
#   {"type": "other",        "text": "..."}   <- not understood; a human must check

_MIN_GRADE = r"\(minimum(?: of)? (\d+) percent\)"
_COURSE_LEAF = re.compile(rf"^(?:({SUBJECT})\s+)?({NUMBER})(?:\s*{_MIN_GRADE})?$")
_CREDITS_LEAF = re.compile(
    rf"^(\d+(?:\.\d+)?|one|two|three|four|five|six)\s+(?:({SUBJECT})\s+)?credits?(?:\s+{_MIN_GRADE})?$",
    re.I,
)
_CREDITS_FROM = re.compile(r"^(\d+(?:\.\d+)?|one|two|three|four|five|six)\s+credits?\s+from\s+(.+)$", re.I)
_OPTION = re.compile(rf"^(?:({SUBJECT}))?\s*({NUMBER})?\s*(?:{_MIN_GRADE})?$")


def _grade(value):
    return int(value) if value else None


def _parse_course_leaf(item: str, last_subject):
    m = _COURSE_LEAF.match(item)
    if not m:
        return None, last_subject
    subject = m.group(1) or last_subject
    if not subject:
        return None, last_subject
    leaf = {"type": "course", "code": f"{subject} {m.group(2)}", "min_grade": _grade(m.group(3))}
    return leaf, subject


def _parse_leaf(item: str, last_subject):
    leaf, subject = _parse_course_leaf(item, last_subject)
    if leaf:
        return leaf, subject

    m = _CREDITS_LEAF.match(item)
    if m:
        return {
            "type": "credits",
            "subject": m.group(2),
            "n": parse_number(m.group(1)),
            "min_grade": _grade(m.group(3)),
        }, last_subject

    if item.lower().startswith("permission of"):
        return {"type": "permission", "text": item}, last_subject

    return {"type": "other", "text": item}, last_subject


def _parse_credits_from(m):
    options, last_subject = [], None
    for item in re.split(r",\s*(?:or\s+|and\s+)?", m.group(2)):
        om = _OPTION.match(item.strip())
        if not om or not (om.group(1) or om.group(2)):
            raise Unparseable(item)
        subject = om.group(1) or last_subject
        last_subject = subject
        code = f"{subject} {om.group(2)}" if om.group(2) else None
        options.append({"subject": subject, "code": code, "min_grade": _grade(om.group(3))})
    return {"type": "credits_from", "n": parse_number(m.group(1)), "options": options}


def _parse_and(part: str):
    """One OR-branch: a list of things that must ALL be satisfied."""
    m = _CREDITS_FROM.match(part)
    if m:
        return _parse_credits_from(m)

    m = re.match(r"^one of (.+)$", part, re.I)
    if m:
        leaves, last_subject = [], None
        for item in re.split(r",\s*(?:or\s+)?", m.group(1)):
            leaf, last_subject = _parse_course_leaf(item.strip(), last_subject)
            if not leaf:
                raise Unparseable(part)
            leaves.append(leaf)
        return {"op": "or", "args": leaves}

    leaves, last_subject = [], None
    for item in re.split(r",\s*(?:and\s+)?|\s+and\s+", part):
        leaf, last_subject = _parse_leaf(item.strip(), last_subject)
        leaves.append(leaf)
    return leaves[0] if len(leaves) == 1 else {"op": "and", "args": leaves}


def _parse_expr(text: str):
    # Requirements that differ by major ("... for GAMP majors; ...") are out of scope.
    if ";" in text or re.search(r"\bfor\b.*\bmajors\b", text):
        raise Unparseable(text)
    # 'and' binds tighter than 'or':  A or B and C  ==  A or (B and C)
    branches = [_parse_and(p.strip()) for p in re.split(r"\s+or\s+", text)]
    return branches[0] if len(branches) == 1 else {"op": "or", "args": branches}


def has_unparsed(expr) -> bool:
    if "op" in expr:
        return any(has_unparsed(a) for a in expr["args"])
    return expr["type"] == "other"


def parse_requirement(raw: str):
    """Turn 'Prerequisite(s): COSC 1P03 (minimum 60 percent), MATH 1P66 and 1P67.'
    into {"raw": ..., "expr": <tree>, "parsed": bool}. Returns None if empty."""
    text = normalize(re.sub(r"^(Prerequisite\(s\)|Corequisite\(s\)|Restriction):", "", raw.strip()))
    text = text.rstrip(".").strip()
    if not text:
        return None
    text = replace_halves(text)
    try:
        expr = _parse_expr(text)
    except Unparseable:
        expr = {"type": "other", "text": text}
    return {"raw": text, "expr": expr, "parsed": not has_unparsed(expr)}



# --------------------------------------------------------------------------- restrictions
#
# A restriction says WHO may enrol ("open to COSC and BCB Co-op students"). It is parsed into:
#   {"raw": str, "open_to": ["COSC", ...], "not_open_to": [...], "minors": ["APCO"],
#    "coop_only": bool, "date_limited": bool, "later_open_to": [...], "later_minors": [...],
#    "conditions": ["major average of at least 75%", ...], "parsed": bool}

_PROGRAM_CODE = re.compile(r"\b[A-Z]{3,4}\b")
_MINOR = re.compile(r"\b([A-Z]{3,4})\s+minors?\b")
_PERMISSION = re.compile(
    r"permission of (?:the )?([A-Za-z][A-Za-z\- ]*?)(?=\s*(?:[,.;)]|$|\band\b|\buntil\b))")


def _program_codes(text: str) -> list[str]:
    return list(dict.fromkeys(_PROGRAM_CODE.findall(text)))


def _split_programs_and_minors(body: str):
    minors = list(dict.fromkeys(_MINOR.findall(body)))
    programs = [c for c in _program_codes(body) if c not in minors]
    return programs, minors


def _restriction_conditions(text: str) -> list[str]:
    conditions = []
    for m in re.finditer(r"minimum (?:of )?(\d+(?:\.\d+)?) percent major average", text):
        conditions.append(f"major average of at least {m.group(1)}%")
    for m in re.finditer(r"minimum (?:of )?(\d+(?:\.\d+)?) overall credits", text):
        conditions.append(f"at least {m.group(1)} overall credits")
    for m in _PERMISSION.finditer(text):
        conditions.append(f"permission of {m.group(1).strip()}")
    return list(dict.fromkeys(conditions))


def parse_restriction(raw: str):
    """Parse 'open to COSC and BCB Co-op students.' etc. into a rule dict (or None if empty)."""
    text = normalize(raw or "").rstrip(".").strip()
    if not text:
        return None

    rule = {"raw": text, "open_to": [], "not_open_to": [], "minors": [], "coop_only": False,
            "date_limited": "until date specified" in text, "later_open_to": [], "later_minors": [],
            "conditions": _restriction_conditions(text), "parsed": True}

    for sentence in re.split(r"(?<=\.)\s+(?=[A-Za-z])", text + "."):
        sentence = sentence.strip().rstrip(".")
        if not sentence:
            continue
        not_open = re.search(r"\bnot open to (.+)", sentence, re.I)
        later = re.match(r"after that date,? open to (.+)", sentence, re.I)
        now = re.search(r"\bopen to (.+)", sentence, re.I)

        if not_open:
            rule["not_open_to"] += _program_codes(not_open.group(1))
        elif later:
            programs, minors = _split_programs_and_minors(later.group(1))
            rule["later_open_to"] += programs
            rule["later_minors"] += minors
        elif now:
            body = now.group(1)
            programs, minors = _split_programs_and_minors(body)
            rule["open_to"] += programs
            rule["minors"] += minors
            if re.search(r"\bco-op students\b", body, re.I):
                rule["coop_only"] = True
        else:
            rule["parsed"] = False  # a sentence we don't recognise

    return rule


# --------------------------------------------------------------------------- page parsing

def _parse_entry(code_p, body) -> dict:
    marker_text = normalize(code_p.get_text())
    m = re.match(rf"^([*#]*)\s*({SUBJECT})\s+(\d[A-Z]\d{{2}}(?:-\d[A-Z]\d{{2}})?)$", marker_text)
    if not m:
        raise ValueError(f"Unexpected course code format: {marker_text!r}")
    marker, subject, number = m.groups()
    code = f"{subject} {number}"

    course = {
        "code": code,
        "subject": subject,
        "number": number,
        "credits": credit_weight(code),
        "title": None,
        "description": None,
        "format": None,
        "prerequisites": None,
        "corequisites": None,
        "restriction": None,
        "restriction_rule": None,
        "notes": [],
        "replaces": [],
        "cross_listed": [],
        "cross_list_marker": {"*": "primary", "#": "secondary"}.get(marker[:1]),
        "data_quality_notes": [],
    }

    for p in body:
        classes = p.get("class", [])
        text = normalize(p.get_text())
        if not text:
            continue

        also = re.search(r"\(also offered as (.+?)\)", text)
        if also:
            # Appears inside the title paragraph or as its own paragraph, depending on the course.
            course["cross_listed"] = extract_codes(also.group(1))
            text = normalize(re.sub(r"\(also offered as .+?\)", "", text))
            if not text:
                continue

        if "calcname" in classes:
            course["title"] = text
        elif "calitalic" in classes:
            course["format"] = text
        elif text.startswith("Prerequisite(s):"):
            course["prerequisites"] = parse_requirement(text)
        elif text.startswith("Corequisite(s):"):
            course["corequisites"] = parse_requirement(text)
        elif text.startswith("Restriction:"):
            course["restriction"] = text.removeprefix("Restriction:").strip()
        elif text.startswith("Completion of this course will replace"):
            course["replaces"] = extract_codes(text)
            course["notes"].append(text)
        elif text.startswith("Note:"):
            course["notes"].append(text.removeprefix("Note:").strip())
        elif course["description"] is None:
            course["description"] = text
        else:
            course["notes"].append(text)

    # The calendar sometimes files a prerequisite under "Restriction:" (e.g. COSC 4P96).
    # A real restriction talks about who may enrol ("open to ... majors").
    r = course["restriction"]
    if r and re.match(rf"^{SUBJECT}\s+{NUMBER}", r) and not re.search(r"\bopen to\b", r, re.I):
        if course["prerequisites"] is None:
            course["prerequisites"] = parse_requirement(r)
        course["data_quality_notes"].append(
            "Calendar lists this under 'Restriction:' but it reads like a prerequisite; "
            "treated as a prerequisite."
        )
        course["restriction"] = None

    course["restriction_rule"] = parse_restriction(course["restriction"]) if course["restriction"] else None
    return course


def parse_calendar_html(html: str) -> dict:
    """Parse a full calendar page into {"calendar_year", "last_updated", "courses": {...}}."""
    soup = BeautifulSoup(html, "html.parser")

    title = soup.title.get_text() if soup.title else ""
    year = re.search(r"(\d{4}-\d{4})", title)
    updated = re.search(r"Last updated:\s*([A-Za-z]+ \d{1,2}, \d{4})", soup.get_text())

    courses = {}
    for code_p in soup.select("p.calccode"):
        body = []
        for sib in code_p.next_siblings:
            if getattr(sib, "name", None) is None:
                continue  # whitespace between tags
            classes = sib.get("class", [])
            # A new course, or a section heading such as "CO-OP COURSES", ends this entry.
            if sib.name != "p" or "calccode" in classes or "courseheading" in classes:
                break
            body.append(sib)
        course = _parse_entry(code_p, body)
        courses[course["code"]] = course

    return {
        "calendar_year": year.group(1) if year else None,
        "last_updated": updated.group(1) if updated else None,
        "courses": courses,
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("html_file", type=Path)
    ap.add_argument("-o", "--output", type=Path, default=Path("data/courses.json"))
    args = ap.parse_args(argv)

    html = args.html_file.read_text(encoding="utf-8", errors="replace")
    data = parse_calendar_html(html)
    data["source_file"] = args.html_file.name

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    courses = data["courses"].values()
    review = [c["code"] for c in courses
              for key in ("prerequisites", "corequisites")
              if c[key] and not c[key]["parsed"]]
    print(f"Parsed {len(data['courses'])} courses ({data['calendar_year']}, updated {data['last_updated']})")
    print(f"Wrote {args.output}")
    if review:
        print(f"{len(review)} requirement(s) need human review: {', '.join(sorted(set(review)))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

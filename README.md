# Brock Course Planner

An agent that helps Brock University Computer Science students plan their courses:
checking prerequisites, minimum grades, and what they're eligible to take next.

> **Status: work in progress.** The data pipeline and prerequisite checker are done and
> tested. The conversational agent layer is next.

## Why this exists

Planning a degree means cross-referencing prerequisites, minimum grades, restrictions, and
co-op patterns across a long calendar. This project turns the calendar into structured data and
gives an AI agent *reliable tools* to answer questions about it, instead of letting a language
model guess at prerequisites.

## Design

The model never decides whether a prerequisite is satisfied. Plain, tested Python does.

```
Calendar HTML ──► parser.py ──► courses.json ──► tools.py ──► agent (next)
                  (HTML →       (structured     (prereq       (decides which tool
                   data)         requirements)   checking)     to call, explains results)
```

- **`planner/parser.py`**: parses Brock's calendar page into JSON. Prerequisites become an
  expression tree (AND / OR / minimum grades / credit counts) rather than text.
- **`planner/tools.py`**: `get_course`, `search`, `check_prereqs`, `available_courses`.
  Results are three-valued: `met`, `not_met`, or `unknown`.
- **Honesty by design:** if a requirement can't be interpreted (for example "4U Mathematics credit" or
  rules that vary by major), the tool returns `unknown` and says why. It never claims a
  prerequisite is met when it can't tell.

## Run it

```bash
pip install -r requirements.txt

# 1. Save the calendar page from your browser into data/raw/ (it's git-ignored)
#    https://brocku.ca/webcal/2024/undergrad/cosc.html
# 2. Parse it
python -m planner.parser data/raw/cosc_2024.html -o data/courses.json

# 3. Try the tools
python - <<'PY'
from planner.tools import Catalog
catalog = Catalog.load()
done = {"COSC 1P02": 85, "COSC 1P03": 90, "MATH 1P66": 88, "MATH 1P67": 80}
print(catalog.check_prereqs("COSC 2P03", done))
PY

# 4. Run the tests
pytest
```

## Known limitations

- **Data is from the 2024-2025 calendar.** Brock's older `webcal` pages stop at that year, so
  results may not match the current calendar. Always confirm with an academic advisor.
- **Course data only covers COSC and APCO courses** from this one page. Prerequisites that
  reference other subjects (MATH, STAT, ...) are still checked, but those courses can't be looked up.
- **Prerequisites that vary by major are not interpreted** (e.g. COSC 2P13 lists different
  prerequisites for different majors). They are flagged `unknown`.
- Not every course runs every term; the timetable is not included.
- Credit weights come from the course code letter (P = 0.5, F = 1.0, Q = 0.25, N = 0).
  The weights for `V` and `C` codes are assumptions; see `planner/parser.py`.

## Roadmap

- [x] Parse course descriptions, prerequisites, restrictions, cross-listings
- [x] Prerequisite / minimum-grade checker with unit tests
- [ ] Handle major-specific prerequisites
- [ ] Parse program requirements (Honours, Co-op pattern)
- [ ] Agent loop using the Claude API with tool use
- [ ] Evaluation set of real planning questions with expected answers
- [ ] Support the current calendar format (calendar.brocku.ca)

## Data source

Course information comes from Brock University's public Undergraduate Calendar. This project is
not affiliated with or endorsed by Brock University.

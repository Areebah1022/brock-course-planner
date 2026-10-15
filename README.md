# Brock Course Planner

An agent that helps Brock University Computer Science students plan their courses:
checking prerequisites, minimum grades, and what they're eligible to take next.

> **Status: work in progress.** The data pipeline, prerequisite checker, and conversational
> agent are built and tested. Next up: major-specific prerequisites and an evaluation set.

## Why this exists

Planning a degree means cross-referencing prerequisites, minimum grades, restrictions, and
co-op patterns across a long calendar. This project turns the calendar into structured data and
gives an AI agent *reliable tools* to answer questions about it, instead of letting a language
model guess at prerequisites.

## Design

The model never decides whether a prerequisite is satisfied. Plain, tested Python does.

```
Calendar HTML ──► parser.py ──► courses.json ──► tools.py ──► agent.py ◄──► Claude API
                  (HTML →       (structured     (prereq       (agent loop:   (decides which
                   data)         requirements)   checking)     runs tools)    tool to call)
```

- **`planner/parser.py`**: parses Brock's calendar page into JSON. Prerequisites become an
  expression tree (AND / OR / minimum grades / credit counts) rather than text.
- **`planner/tools.py`**: `get_course`, `search`, `check_prereqs`, `available_courses`.
  Prerequisite results are three-valued: `met`, `not_met`, or `unknown`.
- **Enrolment restrictions** ("not open to COSC majors", "Co-op students only", "minimum 75%
  major average") are parsed too. Given the student's program and Co-op status, each course gets an
  overall verdict: `eligible`, `not_eligible`, or `check_required`. Courses a student's program
  can't take are hidden, and cross-listed duplicates (COSC 1P50 / APCO 1P50) are shown once.
- **`planner/agent.py`**: the agent loop. Claude reads the student's message and *asks* for tools
  (`update_completed_courses`, `check_prereqs`, `get_course`, `search_courses`,
  `available_courses`, `set_student_profile`). The code runs them and sends the results back until Claude has an answer.
  The student's completed courses live in Python, not in the model's memory.
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

# 3. Add your API key: copy .env.example to .env and paste your key (never commit .env)
#    Get a key at https://console.anthropic.com  (API usage is pay-as-you-go)

# 4. Chat with the planner
python -m planner.agent

# 5. Run the tests (no API key needed; the agent tests use a fake Claude)
pytest
```

Example session (illustrative; exact wording will vary):

```
You: I finished COSC 1P02 with 85, COSC 1P03 with 90, MATH 1P66 with 88 and MATH 1P67 with 80.
     Can I take COSC 2P03?
Planner: Yes, you meet every prerequisite for COSC 2P03. ...
```

Without an API key you can still use the tools directly:

```python
from planner.tools import Catalog
catalog = Catalog.load()
done = {"COSC 1P03": 90, "MATH 1P66": 88, "MATH 1P67": 80}
print(catalog.check_prereqs("COSC 2P03", done))
```

## Known limitations

- **Data is from the 2024-2025 calendar.** Brock's older `webcal` pages stop at that year, so
  results may not match the current calendar. Always confirm with an academic advisor.
- **Course data only covers COSC and APCO courses** from this one page. Prerequisites that
  reference other subjects (MATH, STAT, ...) are still checked, but those courses can't be looked up.
- **Prerequisites that vary by major are not interpreted** (e.g. COSC 2P13 lists different
  prerequisites for different majors). They are flagged `unknown`.
- Restrictions that name extra conditions (a minimum average, overall credits, instructor
  permission) are reported to the student as things to confirm; they are not verified.
- Not every course runs every term; the timetable is not included.
- Credit weights come from the course code letter (P = 0.5, F = 1.0, Q = 0.25, N = 0).
  The weights for `V` and `C` codes are assumptions; see `planner/parser.py`.

## Roadmap

- [x] Parse course descriptions, prerequisites, restrictions, cross-listings
- [x] Prerequisite / minimum-grade checker with unit tests
- [x] Program restrictions (who may enrol), Co-op-only courses, cross-listing de-duplication
- [ ] Handle major-specific prerequisites
- [ ] Parse program requirements (Honours, Co-op pattern)
- [x] Agent loop using the Claude API with tool use
- [ ] Evaluation set of real planning questions with expected answers
- [ ] Support the current calendar format (calendar.brocku.ca)

## Data source

Course information comes from Brock University's public Undergraduate Calendar. This project is
not affiliated with or endorsed by Brock University.

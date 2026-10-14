"""The conversational agent: Claude decides what to do, our tested code does the checking.

How one turn works (this is the whole "agent loop"):

    1. Send the conversation + a list of available tools to Claude.
    2. If Claude answers with text            -> we're done, show it to the student.
    3. If Claude asks to use a tool           -> run that tool in OUR code, send the result back,
                                                 and go to step 1.

Claude never touches your files or data. It can only *ask* for a tool to be run, and we decide
what actually happens. The student's completed courses live in Python (`self.completed`), not in
Claude's memory, so the prerequisite checks always use exact data.

Run it:
    python -m planner.agent
"""

import json
import os
import sys

try:  # Load ANTHROPIC_API_KEY from a local .env file if python-dotenv is installed.
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

from planner.tools import Catalog, normalize_code

# A small, inexpensive model is plenty for tool-driven Q&A. Override with ANTHROPIC_MODEL in .env.
DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-5-5")
MAX_TOKENS = 1500
MAX_TOOL_ROUNDS = 10  # safety net: stop a runaway loop (each round costs money)

SYSTEM_PROMPT = """\
You are a course-planning assistant for Brock University Computer Science students.

Rules:
- You know NOTHING about Brock's courses from memory. Use the tools for every fact about a
  course, prerequisite, or eligibility. Never guess or invent course codes, prerequisites or grades.
- When a student mentions courses they've finished (and grades if they give them), record them
  with update_completed_courses before checking anything. If a grade matters (a prerequisite has
  a minimum percentage) and you don't have it, ask for it.
- check_prereqs returns "met", "not_met" or "unknown". Report "unknown" honestly and explain why
  (for example: the rule varies by major, needs instructor permission, or couldn't be interpreted).
  Never turn "unknown" into a yes.
- The data covers only COSC and APCO courses from one calendar year (stated below). Other subjects,
  program requirements, and the term timetable are NOT included. Say so when relevant.
- Always remind the student to confirm their plan with an academic advisor before registering.
- Be concise and friendly. Use short lists for multi-course answers.
"""

# Each tool is described to Claude with a name, a plain-English description, and a JSON schema
# for its inputs. Claude reads these descriptions to decide when to use each tool.
TOOLS = [
    {
        "name": "update_completed_courses",
        "description": (
            "Record courses the student has completed, with their final percentage grade when "
            "known. Merges into the existing list (re-sending a course updates its grade). "
            "Returns the full list of completed courses."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "courses": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string", "description": "e.g. 'COSC 1P03'"},
                            "grade": {"type": "number", "description": "Final percentage 0-100, if known"},
                        },
                        "required": ["code"],
                    },
                }
            },
            "required": ["courses"],
        },
    },
    {
        "name": "check_prereqs",
        "description": (
            "Check whether the student can take a course, based on their recorded completed "
            "courses. Returns status (met / not_met / unknown), the reasons, and notes about "
            "restrictions and corequisites."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "e.g. 'COSC 3P71'"}},
            "required": ["code"],
        },
    },
    {
        "name": "get_course",
        "description": "Look up one course: title, description, prerequisites, restrictions, notes.",
        "input_schema": {
            "type": "object",
            "properties": {"code": {"type": "string", "description": "e.g. 'COSC 2P03'"}},
            "required": ["code"],
        },
    },
    {
        "name": "search_courses",
        "description": "Search course titles and descriptions by keyword (e.g. 'machine learning').",
        "input_schema": {
            "type": "object",
            "properties": {"keyword": {"type": "string"}},
            "required": ["keyword"],
        },
    },
    {
        "name": "available_courses",
        "description": (
            "List courses the student is eligible for now, or might be (status 'unknown'), "
            "given their recorded completed courses. Optionally filter by subject, e.g. 'COSC'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"subject": {"type": "string", "description": "e.g. 'COSC' (optional)"}},
        },
    },
]


# --------------------------------------------------------------------------- tool execution

def _compact_course(course: dict) -> dict:
    """The fields Claude needs. Prerequisites keep Brock's original wording."""
    prereq, coreq = course["prerequisites"], course["corequisites"]
    return {
        "code": course["code"],
        "title": course["title"],
        "credits": course["credits"],
        "description": course["description"],
        "format": course["format"],
        "prerequisites": prereq["raw"] if prereq else None,
        "prerequisites_fully_understood": prereq["parsed"] if prereq else True,
        "corequisites": coreq["raw"] if coreq else None,
        "restriction": course["restriction"],
        "notes": course["notes"],
    }


def execute_tool(name: str, args: dict, catalog: Catalog, completed: dict):
    """Run one tool and return a JSON-serialisable result. Raises on bad input."""
    if name == "update_completed_courses":
        for item in args["courses"]:
            code = normalize_code(item["code"])
            grade = item.get("grade")
            if grade is not None:
                grade = float(grade)
                if not 0 <= grade <= 100:
                    raise ValueError(f"Grade for {code} must be between 0 and 100, got {grade}")
            completed[code] = grade
        return {"completed_courses": dict(completed)}

    if name == "check_prereqs":
        return catalog.check_prereqs(args["code"], completed)

    if name == "get_course":
        course = catalog.get_course(args["code"])
        if course is None:
            return {"error": f"{normalize_code(args['code'])} is not in the {catalog.calendar_year} data."}
        return _compact_course(course)

    if name == "search_courses":
        hits = catalog.search(args["keyword"], limit=8)
        return {"matches": [{"code": c["code"], "title": c["title"],
                             "summary": (c["description"] or "")[:160]} for c in hits]}

    if name == "available_courses":
        results = catalog.available_courses(completed, subject=args.get("subject"))
        return {"count": len(results),
                "courses": [{"code": r["code"], "title": r["title"], "status": r["status"],
                             "reasons": r["reasons"] if r["status"] == "unknown" else []}
                            for r in results]}

    raise ValueError(f"Unknown tool: {name}")


# --------------------------------------------------------------------------- the agent

def _make_client():
    import anthropic

    return anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment


class Agent:
    def __init__(self, catalog: Catalog, client=None, model: str = DEFAULT_MODEL):
        self.catalog = catalog
        self.client = client or _make_client()
        self.model = model
        self.system = SYSTEM_PROMPT + f"\nData source: Brock {catalog.calendar_year} undergraduate calendar."
        self.messages: list = []     # the conversation so far
        self.completed: dict = {}    # the student's finished courses: {"COSC 1P03": 82.0}
        self.tokens = {"input": 0, "output": 0}

    def chat(self, user_text: str) -> str:
        """Send one student message through the agent loop and return Claude's final reply."""
        start = len(self.messages)
        self.messages.append({"role": "user", "content": user_text})
        try:
            return self._run_loop()
        except Exception:
            del self.messages[start:]  # don't leave a half-finished turn in the history
            raise

    def _run_loop(self) -> str:
        for _ in range(MAX_TOOL_ROUNDS):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=MAX_TOKENS,
                system=self.system,
                tools=TOOLS,
                messages=self.messages,
            )
            self._count_tokens(response)
            self.messages.append({"role": "assistant", "content": response.content})

            tool_calls = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason != "tool_use" or not tool_calls:
                text = "".join(b.text for b in response.content if b.type == "text")
                if response.stop_reason == "max_tokens":
                    text += "\n\n(My answer was cut off. Ask me to continue.)"
                return text

            # Claude asked for tools. Run EVERY requested tool and answer each one, matching ids.
            results = []
            for call in tool_calls:
                try:
                    output = execute_tool(call.name, call.input, self.catalog, self.completed)
                    results.append({"type": "tool_result", "tool_use_id": call.id,
                                    "content": json.dumps(output, ensure_ascii=False)})
                except Exception as exc:  # tell Claude what went wrong so it can recover
                    results.append({"type": "tool_result", "tool_use_id": call.id,
                                    "content": f"Error: {exc}", "is_error": True})
            self.messages.append({"role": "user", "content": results})

        return "Sorry, I got stuck working that out. Could you rephrase or ask a simpler question?"

    def _count_tokens(self, response):
        usage = getattr(response, "usage", None)
        if usage:
            self.tokens["input"] += usage.input_tokens
            self.tokens["output"] += usage.output_tokens


# --------------------------------------------------------------------------- command line

def main() -> int:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("No ANTHROPIC_API_KEY found.\n"
              "Create a file named .env in the project folder containing:\n"
              "    ANTHROPIC_API_KEY=your-key-here")
        return 1

    import anthropic

    agent = Agent(Catalog.load())
    print(f"Brock Course Planner ({agent.catalog.calendar_year} calendar data, model: {agent.model})")
    print("Tell me which courses you've finished, then ask what you can take. Type 'quit' to exit.")

    while True:
        try:
            text = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        if text.lower() in {"quit", "exit"}:
            break
        try:
            print(f"\nPlanner: {agent.chat(text)}")
        except anthropic.AuthenticationError:
            print("\nThe API key was rejected. Check ANTHROPIC_API_KEY in your .env file.")
            return 1
        except anthropic.RateLimitError:
            print("\nRate limited. Wait a moment and try again.")
        except anthropic.APIConnectionError:
            print("\nCouldn't reach the API. Check your internet connection.")
        except anthropic.APIStatusError as exc:
            print(f"\nAPI error {exc.status_code}: {exc.message}")
            if exc.status_code in (400, 402, 403):
                print("(If this mentions credits or billing, check your balance in the Console.)")

    t = agent.tokens
    print(f"\nTokens used this session: {t['input']} in, {t['output']} out.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

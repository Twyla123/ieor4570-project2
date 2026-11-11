"""The research agents: a Lead plans, Researchers look things up in parallel, a Writer reports.

- Lead: reads the conversation, asks the user one question if the request is too vague, and sends tasks to
  researchers. It can go back for more when the findings leave a gap, up to MAX_LEAD_ROUNDS.
- Researchers: one per data source (housing, events, shopping). Each starts in a fresh context with only its own
  instructions and tools, and the researchers of one round run at the same time.
- Writer: turns the findings into one report. It has no tools and may only use what the researchers found.

Each researcher is a dict with name, description, instructions, tools and tool_map. The housing researcher is in
apartment.py and the events researcher in events.py.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

import litellm

from apartment import HOUSING_RESEARCHER
from events import EVENTS_RESEARCHER

# PLACEHOLDER until Alisa adds SHOPPING_RESEARCHER to shopping.py (same shape as HOUSING_RESEARCHER).
# Once shopping.py defines it, the import below is used and this fallback is never built.
try:
    from shopping import SHOPPING_RESEARCHER
except ImportError:
    from shopping import SHOPPING_TOOL, search_products_that_fit

    SHOPPING_RESEARCHER = {
        "name": "shopping",
        "description": (
            "Searches Amazon for furniture and other home items under a budget and checks each product's listed "
            "size against the space the user has. Send it a task when the question is what it costs to furnish "
            "a room or whether an item fits. It cannot compare stores other than Amazon or check stock."
        ),
        "instructions": (
            "You research one task about buying things for a home, using only your tool, and report what it "
            "returned.\n"
            "- Call search_products_that_fit with a short query and the budget from the task. If the task gives "
            "no budget, say so instead of guessing one.\n"
            "- Pass size limits only if the task gives measurements, converted to inches.\n"
            "- Reply with the products that answer the task and nothing else, at most 10 bullets: price, size, "
            "the fit verdict and the product link. Say plainly when a fit is \"maybe\" or \"unknown\".\n"
            "- Use only what the tool returned. Never invent products, prices or sizes.\n"
            "- In a last bullet, say what the search cannot show (Amazon only, prices change) and name any part "
            "of the task it could not answer."
        ),
        "tools": [SHOPPING_TOOL],
        "tool_map": {"search_products_that_fit": search_products_that_fit},
    }

# --- Config ---

MODEL = "vertex_ai/gemini-3.5-flash-lite"
MAX_LEAD_ROUNDS = 3         # the Lead may send researchers out this many times before it has to stop
MAX_RESEARCHER_ROUNDS = 5   # tool rounds for one researcher on one task
MAX_TASKS_PER_ROUND = 4
CALL_TIMEOUT_SECONDS = 90   # one model call
DEADLINE_SECONDS = 240      # graders wait up to 5 minutes for an answer: stop starting new work after this
HISTORY_FOR_WRITER = 6      # latest messages the Writer sees, to know what the user asked

RESEARCHERS = {r["name"]: r for r in (HOUSING_RESEARCHER, EVENTS_RESEARCHER, SHOPPING_RESEARCHER)}


def _today() -> str:
    now = datetime.now(ZoneInfo("America/New_York"))
    return f"Today is {now:%A, %Y-%m-%d} and it is {now:%I:%M %p} in New York."


def _complete(messages: list[dict], tools: list[dict] | None = None):
    """One Gemini call. Returns the reply message."""
    kwargs = {"tools": tools} if tools else {}
    return litellm.completion(
        model=MODEL,
        vertex_location="global",
        messages=messages,
        timeout=CALL_TIMEOUT_SECONDS,
        **kwargs,
    ).choices[0].message


# --- Researchers ---


def _run_tool(tool_map: dict, name: str, args: dict) -> str:
    """Run one tool call. Models invent tool names and arguments; never let that crash the loop."""
    if name not in tool_map:
        return json.dumps({"error": f"Unknown tool '{name}'. Available: {list(tool_map)}"})
    try:
        return tool_map[name](**args)
    except TypeError as e:
        return json.dumps({"error": f"Bad arguments for {name}: {e}"})


def run_researcher(name: str, task: str, deadline: float) -> tuple[str, list[dict]]:
    """Work one task in a fresh context. Returns the report and every tool call it made."""
    researcher = RESEARCHERS[name]
    messages = [
        {"role": "system", "content": f"{researcher['instructions']}\n\n{_today()}"},
        {"role": "user", "content": task},
    ]
    calls = []

    for _ in range(MAX_RESEARCHER_ROUNDS):
        if time.monotonic() > deadline:
            return "Ran out of time before finishing this task.", calls
        try:
            reply = _complete(messages, researcher["tools"])
        except Exception as e:
            return f"The {name} researcher failed: {type(e).__name__}: {str(e)[:200]}", calls
        messages += [reply.model_dump()]

        if not reply.tool_calls:
            return reply.content or "No findings.", calls

        for call in reply.tool_calls:
            try:
                args = json.loads(call.function.arguments)
            except ValueError:
                args = {}
            result = _run_tool(researcher["tool_map"], call.function.name, args)
            calls += [{"agent": name, "name": call.function.name, "args": args, "result": result}]
            messages += [{"role": "tool", "tool_call_id": call.id, "content": result}]

    return "Hit the tool-call limit before finishing this task.", calls


# --- Lead ---


def _researcher_list() -> str:
    return "\n".join(f"- {r['name']}: {r['description']}" for r in RESEARCHERS.values())


def lead_prompt() -> str:
    return (
        "You are the lead of a small research team that helps people settle into New York City: where to live, "
        "what free things there are to do nearby, and what it costs to furnish a room. You do not look anything "
        "up yourself. Your researchers do, and a writer turns what they find into the answer.\n\n"
        f"Your researchers:\n{_researcher_list()}\n\n"
        "How you work:\n"
        "- If the request is too vague for a researcher to act on (for example no neighborhoods to compare, no "
        "budget for furniture, or no idea what the person wants to know), call ask_user with ONE short question. "
        "Do not ask when you can make a sensible plan, and do not ask about things a researcher can default.\n"
        "- Otherwise call research ONCE with a task for every researcher whose data helps, so they work at the "
        "same time. Each researcher starts with an empty memory and sees only its task, so write each task so "
        "it stands alone: name the neighborhoods, dates, addresses, budget and starting place it needs.\n"
        f"- When the findings come back, check them against the question. If a real gap is left, call research "
        f"again with tasks for only that gap. You can send researchers out at most {MAX_LEAD_ROUNDS} times.\n"
        "- When you have enough, reply with the single word READY. Do not write the answer yourself.\n"
        "- If the message is not a research question (a greeting, thanks, or something outside NYC settling "
        "in), reply briefly in plain text without calling anything.\n"
        "- Never answer from your own knowledge of New York.\n\n"
        f"{_today()}"
    )


LEAD_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "research",
            "description": (
                "Send tasks to researchers, who work at the same time, and get back what each one found with its "
                "sources. Send at most one task per researcher."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "description": "One task per researcher whose data helps.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "researcher": {"type": "string", "enum": list(RESEARCHERS), "description": "Which researcher."},
                                "task": {"type": "string", "description": "A self-contained task with every detail the researcher needs."},
                            },
                            "required": ["researcher", "task"],
                        },
                    },
                },
                "required": ["tasks"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "Ask the user one short clarifying question when the request is too vague to research. Ends your turn.",
            "parameters": {
                "type": "object",
                "properties": {"question": {"type": "string", "description": "The question, in one or two sentences."}},
                "required": ["question"],
            },
        },
    },
]


def _research_round(tasks: list[dict], deadline: float) -> tuple[list[dict], list[dict]]:
    """Run one round of tasks in parallel. Returns the findings and every researcher's tool calls."""
    tasks = [t for t in tasks if isinstance(t, dict)][:MAX_TASKS_PER_ROUND]
    findings, calls = [], []
    valid = [t for t in tasks if t.get("researcher") in RESEARCHERS and t.get("task")]
    for t in tasks:
        if t not in valid:
            findings += [{"researcher": str(t.get("researcher")), "task": str(t.get("task")),
                          "report": f"Unknown researcher. Available: {list(RESEARCHERS)}"}]

    if valid:
        with ThreadPoolExecutor(max_workers=len(valid)) as pool:
            outcomes = list(pool.map(lambda t: run_researcher(t["researcher"], t["task"], deadline), valid))
        for t, (report, task_calls) in zip(valid, outcomes):
            findings += [{"researcher": t["researcher"], "task": t["task"], "report": report}]
            calls += task_calls
    return findings, calls


def _findings_text(findings: list[dict]) -> str:
    return "\n\n".join(f"[{f['researcher']} researcher] Task: {f['task']}\n{f['report']}" for f in findings)


# --- Writer ---

WRITER_PROMPT = (
    "You write the final answer for a person settling into New York City, from what the research team found.\n"
    "- Use only the findings below. Add no facts, numbers, places or prices of your own.\n"
    "- Start with a short direct answer to what they asked, then give the evidence, organized by topic (housing "
    "records, free things nearby, furnishing cost). A small table is fine for comparing neighborhoods.\n"
    "- Keep every source link from the findings, as a markdown link right after the fact it supports.\n"
    "- Say \"our estimate\" for anything the findings call an estimate, and never present it as data.\n"
    "- Add a short section, \"What the data can't tell us\", from the limits in the findings, and name any part of "
    "the question the researchers could not answer or failed on. If findings are thin, say so plainly instead of "
    "filling the gap.\n"
    "- Only cover topics the person asked about. Do not mention a topic nobody researched.\n"
    "- Do not tell the person which neighborhood or apartment to pick. Show the evidence and what each choice "
    "trades off.\n"
    "- Plain, friendly, under 400 words."
)


def run_writer(conversation: list[dict], findings: list[dict], stopped_early: bool) -> str:
    recent = [m for m in conversation if m.get("role") in ("user", "assistant") and m.get("content")]
    asked = "\n".join(f"{m['role']}: {m['content']}" for m in recent[-HISTORY_FOR_WRITER:])
    note = "\n\nThe research stopped at its limit, so say that some parts may be missing." if stopped_early else ""
    messages = [
        {"role": "system", "content": f"{WRITER_PROMPT}\n\n{_today()}"},
        {"role": "user", "content": f"The conversation so far:\n{asked}\n\nFindings:\n{_findings_text(findings)}{note}"},
    ]
    try:
        return _complete(messages).content or "I could not write the report."
    except Exception as e:
        return f"The writer failed: {type(e).__name__}: {str(e)[:200]}. The raw findings:\n\n{_findings_text(findings)}"


# --- The harness ---


def run_agent(messages: list[dict]) -> tuple[str, list[dict]]:
    """Answer the latest user message. Returns the final text and a record of every tool call.

    Every record has an "agent" field: the Lead's own calls (research, ask_user) are "lead", and each
    researcher's tool calls carry that researcher's name. The saved history gets only the final answer, not
    the research calls, so later turns stay short.
    """
    deadline = time.monotonic() + DEADLINE_SECONDS
    work = list(messages)  # the Lead's scratch copy: research calls and results stay out of the saved history
    records, findings, last_text = [], [], ""
    stopped_early = False

    for round_no in range(MAX_LEAD_ROUNDS):
        try:
            reply = _complete(work, LEAD_TOOLS)
        except Exception as e:
            text = f"Model call failed: {type(e).__name__}: {str(e)[:300]}"
            messages += [{"role": "assistant", "content": text}]
            return text, records
        work += [reply.model_dump()]
        last_text = reply.content or ""

        if not reply.tool_calls:
            break  # READY, or a plain answer to a message that was not a research question

        # A question for the user ends the turn.
        ask = next((c for c in reply.tool_calls if c.function.name == "ask_user"), None)
        if ask:
            question = json.loads(ask.function.arguments or "{}").get("question") or "Could you tell me a bit more?"
            records += [{"agent": "lead", "name": "ask_user", "args": {"question": question}, "result": "Asked the user."}]
            messages += [{"role": "assistant", "content": question}]
            return question, records

        for call in reply.tool_calls:
            try:
                args = json.loads(call.function.arguments)
            except ValueError:
                args = {}
            if call.function.name != "research":
                work += [{"role": "tool", "tool_call_id": call.id,
                          "content": json.dumps({"error": f"Unknown tool '{call.function.name}'. Use research or ask_user."})}]
                continue
            record = {"agent": "lead", "name": "research", "args": args, "result": ""}
            records += [record]
            round_findings, round_calls = _research_round(args.get("tasks") or [], deadline)
            findings += round_findings
            records += round_calls
            record["result"] = _findings_text(round_findings) or "No valid tasks."
            work += [{"role": "tool", "tool_call_id": call.id, "content": record["result"]}]

        if round_no == MAX_LEAD_ROUNDS - 1 or time.monotonic() > deadline:
            stopped_early = True  # the Lead was still asking for research when the limit or the clock ran out
            break

    if not findings:
        # Nothing to research: a greeting, thanks, or something outside the project.
        text = last_text if last_text.strip().upper() != "READY" else "What would you like to know about settling into New York?"
        messages += [{"role": "assistant", "content": text}]
        return text, records

    report = run_writer(messages, findings, stopped_early)
    messages += [{"role": "assistant", "content": report}]
    return report, records

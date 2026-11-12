"""The agent loop — what turns KAI from a chatbot into an agent.

A chatbot does one round trip: messages in, text out. The agent loop
keeps going:

    1. Send the conversation + the tool catalogue to the model.
    2. If the model answers with text → done, that's the reply.
    3. If the model answers with tool_calls → run each tool, append
       every result as a "tool" message, and go back to 1.
    4. MAX_STEPS caps the rounds so the loop can never spin forever;
       on the final round the model must answer with the tools off.

Every tool execution is recorded in a trace — [{tool, args, result}] —
which is saved with the assistant's message and shown in the UI, so
the user can see exactly what KAI did.
"""

import json
import re

from . import ai, bundles, coding_tools, tools

MAX_STEPS = 6
CODING_MAX_STEPS = 14
MAX_PLAN_STEPS = 8
AGENT_NOTE = (
    " You have tools available (calculator, current_datetime, weather, "
    "web_search, fetch_page). Use them whenever a question needs exact "
    "maths, the current date/time, live weather, or current information "
    "from the web — never guess those. When you answer from the web, "
    "cite the URLs you actually opened."
)
CODING_NOTE = (
    " You are in CODING MODE. You also have coding tools that work "
    "inside one sandboxed workspace folder: list_files, read_file, "
    "write_file, edit_file, search_code, and run_command (allowlisted: "
    "python, node, npm test/run, git status/diff/log). Discipline: "
    "explore first (list_files/search_code) before editing; prefer "
    "edit_file over rewriting whole files; after EVERY change run the "
    "tests with run_command, read failures carefully, and fix them; "
    "finish with a short summary of what you changed."
)


def _dispatch(name, args):
    result = coding_tools.run_coding_tool(name, args)
    if result is not None:
        return result
    return tools.run_tool(name, args)


def _resolve_provider(messages, choice):
    """Which provider/model an agent run uses: the literal choice
    "auto" resolves through the task router on the latest user
    message; any other choice goes through agent_provider. Shared
    by run_agent and make_plan so planning and execution can never
    disagree about the model."""
    if choice == "auto":
        return ai.route_task(messages)
    return ai.agent_provider(choice)


_STEP_LINE = re.compile(r"^\s*(?:\d+[.)]\s+|[-*•]\s+)(.+?)\s*$")


def parse_plan(text):
    """Numbered/bulleted lines → plan steps (max MAX_PLAN_STEPS).
    Unparseable text becomes a single step — a plan the model
    phrased as prose is still a plan, and the user reviews it
    before anything runs."""
    steps = []
    for line in (text or "").splitlines():
        match = _STEP_LINE.match(line)
        if match and match.group(1):
            steps.append(match.group(1)[:300])
        if len(steps) >= MAX_PLAN_STEPS:
            break
    if not steps and (text or "").strip():
        steps = [text.strip()[:300]]
    return steps


def make_plan(messages, choice=None, bundle=None, on_usage=None):
    """Plan-then-execute, step 1 (Phase 6): ask the model to break
    the request into steps WITHOUT running any tools. Returns the
    step list, or None when the provider never answered. The plan
    is a preview — nothing is saved and no tool runs until the
    user approves it and run_agent executes with plan=...."""
    provider, model = _resolve_provider(messages, choice)
    if bundle:
        tool_names = ", ".join(bundles.BUNDLES[bundle])
    else:
        tool_names = "all available tools"
    planning = [dict(m) for m in messages]
    planning.append(
        {
            "role": "user",
            "content": (
                "Break the request above into a short numbered plan "
                f"(at most {MAX_PLAN_STEPS} steps) using {tool_names}. "
                "Each step is one action naming the tool it needs. "
                "Reply with ONLY the numbered list, no preamble."
            ),
        }
    )
    try:
        message = ai.chat_completion(
            provider, planning, model, tools=None, on_usage=on_usage
        )
    except Exception:
        return None
    if message is None:
        return None
    return parse_plan(message.get("content") or "")


def _verify_completion(provider, model, messages, plan, reply, trace,
                       on_usage=None):
    """Completion verification (Phase 6): one tools-off call asking
    whether the reply actually completed the request, given the
    plan (if any) and what the tools returned. Returns a trace
    entry, or None when verification itself fails — verification
    must never break a reply that already exists. Only called when
    tools actually ran: a plain answer has nothing to verify."""
    request_text = ""
    for message in reversed(messages):
        if message.get("role") == "user":
            request_text = message.get("content") or ""
            break
    tool_summary = "; ".join(
        f"{step['tool']}: {step['result'][:200]}"
        for step in trace
        if step["tool"] not in ("plan", "verify_completion")
    )
    plan_text = (
        "\n".join(f"{i}. {s}" for i, s in enumerate(plan, 1))
        if plan
        else "(no plan — direct execution)"
    )
    try:
        message = ai.chat_completion(
            provider,
            [
                {
                    "role": "system",
                    "content": (
                        "You verify whether an AI assistant completed "
                        "the user's request. Reply with YES or NO on "
                        "the first line, then one short sentence "
                        "explaining what is missing (or 'Nothing "
                        "missing.')."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Request: {request_text}\n\nPlan:\n{plan_text}\n\n"
                        f"Tool results: {tool_summary}\n\n"
                        f"Reply: {reply}"
                    ),
                },
            ],
            model,
            tools=None,
            on_usage=on_usage,
        )
    except Exception:
        return None
    if message is None:
        return None
    text = (message.get("content") or "").strip()
    lines = text.splitlines()
    first = lines[0].strip().upper() if lines else ""
    complete = first.startswith("YES")
    note = " ".join(lines[1:]).strip()[:300] or "No explanation given."
    return {
        "tool": "verify_completion",
        "args": {},
        "result": f"complete: {'yes' if complete else 'no'} — {note}",
    }


def _clean_plan(plan):
    """Plan steps as run_agent accepts them: strings only, stripped,
    capped. Anything else is dropped — a malformed plan must not
    reach the system prompt."""
    if not isinstance(plan, list):
        return []
    steps = []
    for step in plan:
        if isinstance(step, str) and step.strip():
            steps.append(step.strip()[:300])
        if len(steps) >= MAX_PLAN_STEPS:
            break
    return steps


def run_agent(messages, choice=None, coding=False, on_usage=None,
              plan=None, bundle=None):
    """Run the loop. `messages` is the chat history incl. a system
    message. Returns (reply_text, trace) — reply_text is None only
    when the provider never answered at all. The literal choice
    "auto" resolves through the task router (route_task) on the
    latest user message; any other choice goes through
    agent_provider. `on_usage` is forwarded to every
    chat_completion call for the cost ledger (one row per call).

    Phase 6: `bundle` restricts the offered tools to a named
    bundle (None = every base tool, as before). `plan` is an
    already-approved step list: it is recorded as the first trace
    entry and appended to the system prompt, so execution follows
    what the user reviewed. After a clean finish, a verification
    call checks completion and appends a verify_completion trace
    entry (never on provider failure, and never when no tool ran).
    """
    plan = _clean_plan(plan)
    if bundle is not None:
        schemas = bundles.schemas_for(bundle)
    else:
        schemas = list(tools.TOOL_SCHEMAS)
    max_steps = MAX_STEPS
    note = AGENT_NOTE
    if coding:
        seen = {s["function"]["name"] for s in schemas}
        schemas += [
            s for s in coding_tools.CODING_TOOL_SCHEMAS
            if s["function"]["name"] not in seen
        ]
        max_steps = CODING_MAX_STEPS
        note = CODING_NOTE
    if bundles.includes_coding_tools(schemas) and not (
        coding_tools.execution_enabled()
    ):
        # Defense in depth (Phase 1 Step 0): the API view rejects
        # coding requests first, but no caller of the agent may ever
        # reach the coding tools while the server-side switch is off
        # — whether they arrived via the coding flag or the coding
        # bundle.
        return (
            "Coding mode is disabled on this server.",
            [],
        )
    provider, model = _resolve_provider(messages, choice)
    working = [dict(m) for m in messages]
    if working and working[0].get("role") == "system":
        working[0]["content"] = working[0]["content"] + note
        if plan:
            steps_text = "\n".join(
                f"{i}. {s}" for i, s in enumerate(plan, 1)
            )
            working[0]["content"] += (
                "\n\nThe user approved this plan — follow it:\n"
                f"{steps_text}"
            )

    trace = []
    if plan:
        trace.append(
            {
                "tool": "plan",
                "args": {"steps": plan},
                "result": f"Approved plan ({len(plan)} steps)",
            }
        )
    for step in range(max_steps):
        last_round = step == max_steps - 1
        message = ai.chat_completion(
            provider,
            working,
            model,
            tools=None if last_round else schemas,
            on_usage=on_usage,
        )
        if message is None:
            return None, trace

        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            reply = message.get("content") or ""
            if trace:
                verified = _verify_completion(
                    provider, model, messages, plan, reply, trace,
                    on_usage=on_usage,
                )
                if verified is not None:
                    trace.append(verified)
            return reply, trace

        # The assistant's tool-call message must go back verbatim —
        # the API pairs each tool result to its call by id.
        working.append(message)
        for call in tool_calls:
            function = call.get("function") or {}
            name = function.get("name", "")
            try:
                args = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            result = _dispatch(name, args)
            trace.append(
                {"tool": name, "args": args, "result": result[:600]}
            )
            working.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id", ""),
                    "content": result,
                }
            )
    # Step budget exhausted (or a provider returned tool calls even
    # with tools off): one final no-tools attempt so the user still
    # gets an answer built from everything the tools returned.
    message = ai.chat_completion(
        provider, working, model, tools=None, on_usage=on_usage
    )
    if message is not None and not (message.get("tool_calls") or []):
        reply = message.get("content") or ""
        if trace:
            verified = _verify_completion(
                provider, model, messages, plan, reply, trace,
                on_usage=on_usage,
            )
            if verified is not None:
                trace.append(verified)
        return reply, trace
    return (
        "I ran my tools but couldn't finish in the step budget — "
        "here's what I found: " + "; ".join(t["result"] for t in trace),
        trace,
    )

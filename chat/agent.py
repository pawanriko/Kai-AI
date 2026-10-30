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

from . import ai, coding_tools, tools

MAX_STEPS = 6
CODING_MAX_STEPS = 14
AGENT_NOTE = (
    " You have tools available (calculator, current_datetime, weather). "
    "Use them whenever a question needs exact maths, the current "
    "date/time, or live weather — never guess those."
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


def run_agent(messages, choice=None, coding=False):
    """Run the loop. `messages` is the chat history incl. a system
    message. Returns (reply_text, trace) — reply_text is None only
    when the provider never answered at all."""
    provider, model = ai.agent_provider(choice)
    schemas = list(tools.TOOL_SCHEMAS)
    max_steps = MAX_STEPS
    note = AGENT_NOTE
    if coding:
        schemas += coding_tools.CODING_TOOL_SCHEMAS
        max_steps = CODING_MAX_STEPS
        note = CODING_NOTE
    working = [dict(m) for m in messages]
    if working and working[0].get("role") == "system":
        working[0]["content"] = working[0]["content"] + note

    trace = []
    for step in range(max_steps):
        last_round = step == max_steps - 1
        message = ai.chat_completion(
            provider,
            working,
            model,
            tools=None if last_round else schemas,
        )
        if message is None:
            return None, trace

        tool_calls = message.get("tool_calls") or []
        if not tool_calls:
            return message.get("content") or "", trace

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
    message = ai.chat_completion(provider, working, model, tools=None)
    if message is not None and not (message.get("tool_calls") or []):
        return message.get("content") or "", trace
    return (
        "I ran my tools but couldn't finish in the step budget — "
        "here's what I found: " + "; ".join(t["result"] for t in trace),
        trace,
    )

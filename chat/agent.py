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

from . import ai, tools

MAX_STEPS = 6
AGENT_NOTE = (
    " You have tools available (calculator, current_datetime, weather). "
    "Use them whenever a question needs exact maths, the current "
    "date/time, or live weather — never guess those."
)


def run_agent(messages, choice=None):
    """Run the loop. `messages` is the chat history incl. a system
    message. Returns (reply_text, trace) — reply_text is None only
    when the provider never answered at all."""
    provider, model = ai.agent_provider(choice)
    working = [dict(m) for m in messages]
    if working and working[0].get("role") == "system":
        working[0]["content"] = working[0]["content"] + AGENT_NOTE

    trace = []
    for step in range(MAX_STEPS):
        last_round = step == MAX_STEPS - 1
        message = ai.chat_completion(
            provider,
            working,
            model,
            tools=None if last_round else tools.TOOL_SCHEMAS,
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
            result = tools.run_tool(name, args)
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

"""Research reports (Phase 5): Markdown exports of a conversation
whose sources come ONLY from the stored agent traces.

Citations or it didn't happen: the Sources section lists URLs the
agent actually used — fetch_page URLs from trace args, plus URLs
mined from web_search result text. When a conversation has no
recorded sources the report says so plainly instead of inventing
citations. The trace stores each tool result truncated to 600
characters, so web_search citations are limited to what survived
that cap; fetch_page sources are complete because the URL lives
in the trace args.
"""

from .research import extract_urls


def conversation_sources(messages):
    """Deduplicated source URLs from assistant messages' traces,
    in first-seen order."""
    sources = []
    seen = set()
    for message in messages:
        if getattr(message, "role", None) != "assistant":
            continue
        for step in getattr(message, "trace", None) or []:
            tool = step.get("tool", "")
            args = step.get("args") or {}
            if tool == "fetch_page" and args.get("url"):
                candidates = [args["url"]]
            else:
                candidates = extract_urls(step.get("result") or "")
            for url in candidates:
                if url not in seen:
                    seen.add(url)
                    sources.append(url)
    return sources


def build_report(title, messages):
    """The full Markdown report: the conversation, then Sources."""
    lines = [f"# {title}", ""]
    for message in messages:
        role = getattr(message, "role", "")
        content = getattr(message, "content", "")
        if role == "user":
            lines.append(f"**You:** {content}")
        elif role == "assistant":
            lines.append(f"**KAI:** {content}")
        else:
            continue
        lines.append("")
    sources = conversation_sources(messages)
    lines.append("## Sources")
    lines.append("")
    if sources:
        for i, url in enumerate(sources, 1):
            lines.append(f"{i}. {url}")
    else:
        lines.append("_No sources were recorded for this conversation._")
    lines.append("")
    return "\n".join(lines)

"""Named tool bundles (Phase 6): named subsets of the ONE tool
registry — not separate agent codebases.

A bundle restricts which tools the orchestrator offers the model:
research work gets the web tools, coding work gets the workspace
tools, productivity gets everything except the workspace tools.
The default (no bundle) offers every base tool, exactly as before
— bundles are opt-in, so existing agent behavior is unchanged
unless the user picks one.

The coding bundle is gated like coding mode itself: its schemas
include the workspace tools, and the orchestrator refuses to run
them while the server-side kill switch is off (see agent.py).
"""

from . import coding_tools, tools

BUNDLES = {
    "research": ["web_search", "fetch_page", "current_datetime"],
    "productivity": [
        "calculator",
        "current_datetime",
        "weather",
        "web_search",
        "fetch_page",
    ],
    "coding": [
        "list_files",
        "read_file",
        "write_file",
        "edit_file",
        "search_code",
        "run_command",
        "calculator",
        "current_datetime",
    ],
}

CODING_TOOL_NAMES = frozenset(
    schema["function"]["name"]
    for schema in coding_tools.CODING_TOOL_SCHEMAS
)


def _registry():
    """Every known tool name → its schema, from both registries."""
    schemas = {}
    for schema in tools.TOOL_SCHEMAS + coding_tools.CODING_TOOL_SCHEMAS:
        schemas[schema["function"]["name"]] = schema
    return schemas


def schemas_for(bundle):
    """The schemas for a bundle name. Raises ValueError for an
    unknown bundle (the view turns it into a 400)."""
    if bundle not in BUNDLES:
        raise ValueError(f"unknown tool bundle: {bundle}")
    registry = _registry()
    return [registry[name] for name in BUNDLES[bundle]]


def includes_coding_tools(schemas):
    """True when a schema list offers any workspace tool — the
    condition the kill switch guards."""
    return any(
        schema["function"]["name"] in CODING_TOOL_NAMES
        for schema in schemas
    )

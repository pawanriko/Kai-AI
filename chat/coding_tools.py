"""Coding tools — the agent's hands for code (phase 2).

Everything is confined to ONE sandbox folder, the workspace root:
the KAI_WORKSPACE env var, or <project>/agent_workspace/ by default.
Every path a tool receives is resolved and checked against that root;
anything that escapes (../, absolute paths elsewhere, symlinks out)
is refused. The shell tool runs an ALLOWLIST of commands only, with
no shell (arguments are split, never interpreted), a timeout, and
truncated output.

Tools return strings, like all KAI tools — errors come back as text
the model can react to.
"""

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

from django.conf import settings

MAX_READ_CHARS = 20000
MAX_OUTPUT_CHARS = 6000

# ---------------------------------------------------------------- schemas

CODING_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": (
                "List the files in the coding workspace (or one of its "
                "subfolders) so you can see the project structure before "
                "reading or editing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "folder": {
                        "type": "string",
                        "description": "Relative folder, default '' (root)",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the coding workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path, e.g. 'app/main.py'",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Create a file in the coding workspace, or overwrite it "
                "completely. Parent folders are created as needed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": (
                "Replace an exact piece of text inside a workspace file. "
                "old_text must match exactly once — prefer this over "
                "rewriting whole files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": (
                "Search the workspace for a text pattern; returns "
                "matching lines as path:line: text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": (
                "Run an allowlisted command in the workspace root: "
                "python, python -m pytest / unittest, node, npm test, "
                "git status/diff/log. 30s timeout. Use it to run tests "
                "after every change and read the failures."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "e.g. 'python -m pytest -q'",
                    }
                },
                "required": ["command"],
            },
        },
    },
]

# ---------------------------------------------------------------- sandbox

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "dist"}


def workspace_root():
    root = os.environ.get("KAI_WORKSPACE") or str(
        Path(settings.BASE_DIR) / "agent_workspace"
    )
    path = Path(root).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_path(relative):
    """Resolve `relative` inside the workspace; None if it escapes."""
    root = workspace_root()
    target = (root / relative).resolve()
    if target != root and root not in target.parents:
        return None
    return target


# ---------------------------------------------------------------- file tools

def list_files(folder=""):
    target = _safe_path(folder or ".")
    if target is None:
        return "Error: that folder is outside the workspace."
    if not target.exists():
        return f"Error: '{folder}' does not exist in the workspace."
    root = workspace_root()
    lines = []
    for path in sorted(target.rglob("*")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        rel = path.relative_to(root)
        lines.append(f"{rel}/" if path.is_dir() else str(rel))
        if len(lines) >= 200:
            lines.append("… (truncated at 200 entries)")
            break
    return "\n".join(lines) if lines else "(workspace is empty)"


def read_file(path):
    target = _safe_path(path)
    if target is None:
        return "Error: that path is outside the workspace."
    if not target.is_file():
        return f"Error: '{path}' is not a file in the workspace."
    text = target.read_text(encoding="utf-8", errors="replace")
    if len(text) > MAX_READ_CHARS:
        text = text[:MAX_READ_CHARS] + "\n… (file truncated)"
    return text


def write_file(path, content):
    target = _safe_path(path)
    if target is None:
        return "Error: that path is outside the workspace."
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Wrote {path} ({len(content)} characters)."


def edit_file(path, old_text, new_text):
    target = _safe_path(path)
    if target is None:
        return "Error: that path is outside the workspace."
    if not target.is_file():
        return f"Error: '{path}' is not a file in the workspace."
    text = target.read_text(encoding="utf-8")
    count = text.count(old_text)
    if count == 0:
        return f"Error: old_text not found in {path}."
    if count > 1:
        return (
            f"Error: old_text appears {count} times in {path}; "
            "include more surrounding text so it matches exactly once."
        )
    target.write_text(text.replace(old_text, new_text), encoding="utf-8")
    return f"Edited {path} (1 replacement)."


def search_code(pattern):
    root = workspace_root()
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return f"Error: bad pattern: {exc}"
    hits = []
    for path in sorted(root.rglob("*")):
        if path.is_dir() or any(p in _SKIP_DIRS for p in path.parts):
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue
        for number, line in enumerate(lines, 1):
            if regex.search(line):
                hits.append(
                    f"{path.relative_to(root)}:{number}: {line.strip()[:160]}"
                )
                if len(hits) >= 60:
                    return "\n".join(hits) + "\n… (truncated at 60 matches)"
    return "\n".join(hits) if hits else f"No matches for '{pattern}'."


# ---------------------------------------------------------------- shell tool

_ALLOWED = [
    ("python",),
    ("python3",),
    ("py",),
    ("node",),
    ("npm", "test"),
    ("npm", "run"),
    ("git", "status"),
    ("git", "diff"),
    ("git", "log"),
]
# python may only run a script inside the workspace or a safe module.
_ALLOWED_PY_MODULES = {"pytest", "unittest", "pip"}


def _command_allowed(argv):
    if not argv:
        return False
    for prefix in _ALLOWED:
        if tuple(argv[: len(prefix)]) == prefix:
            if prefix[0] in ("python", "python3", "py") and "-m" in argv:
                module = argv[argv.index("-m") + 1] if argv.index("-m") + 1 < len(argv) else ""
                return module.split(".")[0] in _ALLOWED_PY_MODULES
            return True
    return False


def run_command(command):
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return f"Error: could not parse the command: {exc}"
    if not _command_allowed(argv):
        return (
            "Error: command not allowed. Allowed: python [script.py | "
            "-m pytest/unittest/pip ...], node, npm test, npm run, "
            "git status/diff/log."
        )
    # Running "python" must mean THIS project's interpreter.
    if argv[0] in ("python", "python3", "py"):
        argv[0] = sys.executable
    try:
        done = subprocess.run(
            argv,
            cwd=workspace_root(),
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return "Error: command timed out after 30 seconds."
    except Exception as exc:
        return f"Error: could not run the command: {exc}"
    output = (done.stdout or "") + (done.stderr or "")
    output = output.strip() or "(no output)"
    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + "\n… (output truncated)"
    return f"exit code {done.returncode}\n{output}"


# ---------------------------------------------------------------- dispatch

_CODING_TOOLS = {
    "list_files": list_files,
    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    "search_code": search_code,
    "run_command": run_command,
}


def run_coding_tool(name, args):
    function = _CODING_TOOLS.get(name)
    if function is None:
        return None  # not a coding tool — let the caller try others
    try:
        return str(function(**(args or {})))
    except TypeError as exc:
        return f"Error: bad arguments for {name}: {exc}"
    except Exception as exc:
        return f"Error: {name} failed: {exc}"

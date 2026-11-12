"""Open Interpreter interface (Phase 8) — the computer-control
half of automation, WITHOUT rebuilding Open Interpreter.

Open Interpreter is already installed on Pawan's PC (0.0.58,
sandboxed to E:\\oi-test, approval-gated). KAI on Render cannot
reach that PC directly, so this client talks to a small bridge
HTTP endpoint that must run on the PC beside OI:

    POST {KAI_OI_BRIDGE_URL}/run
    {"command": "<natural-language instruction>", "cwd": "<folder>"?}
    → {"output": "<OI transcript>", "exit_code": 0}

The bridge itself is NOT built here — it lives on his PC, and no
live OI run has happened from KAI. Until KAI_OI_BRIDGE_URL is set
in the server environment, every computer action fails with a
clear "not configured" message: the approval/audit spine ships
now; the live connection is deferred and must be verified from
his PC before any real command runs through it.

The client never invents commands: it forwards exactly the
approved payload, and the bridge is expected to run OI with its
own approval gates intact.
"""

import json
import os
import urllib.error
import urllib.request

_MAX_OUTPUT_CHARS = 4000
_TIMEOUT = 120


class OIClient:
    """Forwards an approved instruction to the OI bridge on the PC."""

    def __init__(self, bridge_url=None):
        self._bridge_url = bridge_url
        if self._bridge_url is None:
            self._bridge_url = os.environ.get("KAI_OI_BRIDGE_URL", "")

    def run(self, action, payload):
        if action != "run":
            raise ValueError(f"unknown computer action: {action}")
        if not self._bridge_url:
            raise RuntimeError(
                "Open Interpreter bridge is not configured "
                "(KAI_OI_BRIDGE_URL is unset) — no command was sent."
            )
        body = json.dumps(
            {
                "command": (payload or {}).get("command", ""),
                "cwd": (payload or {}).get("cwd", ""),
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self._bridge_url.rstrip("/") + "/run",
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "KAI/2.0 (personal assistant)",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=_TIMEOUT
            ) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, ValueError) as exc:
            raise RuntimeError(f"OI bridge unreachable or invalid: {exc}")
        output = str(result.get("output", ""))[:_MAX_OUTPUT_CHARS]
        return f"exit {result.get('exit_code')}\n{output}"

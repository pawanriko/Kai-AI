"""n8n interface (Phase 8) — config/interface only.

n8n is self-hosted and free; KAI holds NO live n8n instance and
no workflow definitions. The interface is the standard trigger
mechanism: a workflow exposes a Webhook URL, and triggering it is
an HTTP POST of a JSON payload to that URL. The user pastes the
webhook URL into the action payload when proposing the trigger —
KAI never guesses URLs, and there is no n8n API-key management
in this phase (webhook URLs are the capability; keep them out of
shared screenshots).

No live n8n verification has happened from here: there is no
instance to call. The approval/audit spine and this trigger
interface ship now; wiring a real self-hosted n8n is Pawan's
setup step, documented in docs/AUTOMATION.md.
"""

import json
import urllib.error
import urllib.parse
import urllib.request

_TIMEOUT = 30
_MAX_BODY_CHARS = 500


class N8nClient:
    """Triggers an n8n workflow through its webhook URL."""

    def run(self, action, payload):
        if action != "trigger":
            raise ValueError(f"unknown workflow action: {action}")
        webhook_url = (payload or {}).get("webhook_url", "")
        parsed = urllib.parse.urlparse(webhook_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("webhook_url must be an http(s) URL")
        body = json.dumps((payload or {}).get("data") or {}).encode("utf-8")
        request = urllib.request.Request(
            webhook_url,
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
                text = response.read().decode("utf-8", errors="replace")
                status = response.status
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"n8n webhook returned HTTP {exc.code}: "
                f"{text[:_MAX_BODY_CHARS]}"
            )
        except urllib.error.URLError as exc:
            raise RuntimeError(f"n8n webhook unreachable: {exc}")
        return (
            f"n8n workflow triggered (HTTP {status}): "
            f"{text[:_MAX_BODY_CHARS]}"
        )

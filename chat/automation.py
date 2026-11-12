"""Automation service (Phase 8): propose → approve/deny → execute,
with an audit entry for every transition.

Default-deny is enforced HERE, not just in the views: execute
refuses anything that is not APPROVED, and the final status
write is a conditional update (only a row still APPROVED flips
to EXECUTED/FAILED), so a racing second execute cannot record
a second outcome. Views own ownership (404s) and HTTP mapping;
this module owns the state machine and the audit trail.
"""

import urllib.parse

from django.utils import timezone

from .browser_agent import BrowserRunner
from .models import AuditLog, AutomationAction
from .n8n_client import N8nClient
from .oi_client import OIClient

ALLOWED_ACTIONS = {
    AutomationAction.Target.BROWSER: {
        "navigate": ("url",),
        "click": ("url", "selector"),
        "type": ("url", "selector", "text"),
        "extract": ("url",),
    },
    AutomationAction.Target.COMPUTER: {
        "run": ("command",),
    },
    AutomationAction.Target.WORKFLOW: {
        "trigger": ("webhook_url",),
    },
}

_MAX_RESULT_CHARS = 4000


def _audit(action, event, detail=""):
    AuditLog.objects.create(
        user=action.user,
        action_pk=action.pk,
        target=action.target,
        action_name=action.action,
        description=action.description,
        event=event,
        detail=detail[:1000],
    )


def _validate_payload(target, action, payload):
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    required = ALLOWED_ACTIONS[target][action]
    for key in required:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"payload.{key} is required")
    url = payload.get("url") or payload.get("webhook_url")
    if url:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("payload URL must be an http(s) URL")


def propose_action(user, target, action, payload, description):
    """Create a PENDING action + audit entry. Raises ValueError on
    any invalid field — nothing is stored for a bad proposal."""
    if target not in ALLOWED_ACTIONS:
        raise ValueError(f"unknown automation target: {target}")
    if action not in ALLOWED_ACTIONS[target]:
        raise ValueError(f"unknown action for {target}: {action}")
    description = (description or "").strip()
    if not description:
        raise ValueError("description is required")
    _validate_payload(target, action, payload or {})
    created = AutomationAction.objects.create(
        user=user,
        target=target,
        action=action,
        payload=payload or {},
        description=description[:300],
    )
    _audit(created, AuditLog.Event.PROPOSED)
    return created


def decide_action(action, approve):
    """Approve or deny a PENDING action. Raises ValueError when the
    action is no longer pending — a decided action stays decided."""
    if action.status != AutomationAction.Status.PENDING:
        raise ValueError(
            f"only pending actions can be decided (now {action.status})"
        )
    action.status = (
        AutomationAction.Status.APPROVED
        if approve
        else AutomationAction.Status.DENIED
    )
    action.decided_at = timezone.now()
    action.save(update_fields=["status", "decided_at"])
    _audit(
        action,
        AuditLog.Event.APPROVED if approve else AuditLog.Event.DENIED,
    )
    return action


def get_runner(target):
    """The runner for a target. A module-level seam so tests can
    substitute fakes with mock.patch; production always builds
    the real runners."""
    if target == AutomationAction.Target.BROWSER:
        return BrowserRunner()
    if target == AutomationAction.Target.COMPUTER:
        return OIClient()
    return N8nClient()


def execute_action(action):
    """Run an APPROVED action through its runner and record the
    outcome. Default-deny: anything not APPROVED raises
    PermissionError and the runner is never touched. A completed
    action raises ValueError. Runner failures become FAILED with
    the error as the result — never an exception to the caller."""
    if action.status in (
        AutomationAction.Status.EXECUTED,
        AutomationAction.Status.FAILED,
    ):
        raise ValueError(f"action already completed ({action.status})")
    if action.status != AutomationAction.Status.APPROVED:
        raise PermissionError(
            f"action has not been approved (now {action.status})"
        )
    try:
        result = get_runner(action.target).run(action.action, action.payload)
        status = AutomationAction.Status.EXECUTED
        event = AuditLog.Event.EXECUTED
    except Exception as exc:
        result = str(exc)
        status = AutomationAction.Status.FAILED
        event = AuditLog.Event.FAILED
    # Conditional write: only a row STILL approved flips. If a
    # racing execute already recorded an outcome, updated == 0
    # and the race is reported instead of overwriting history.
    updated = AutomationAction.objects.filter(
        pk=action.pk, status=AutomationAction.Status.APPROVED
    ).update(
        status=status,
        result=result[:_MAX_RESULT_CHARS],
        executed_at=timezone.now(),
    )
    if updated == 0:
        raise ValueError("action was already completed by another execute")
    action.refresh_from_db()
    _audit(action, event, detail=result[:1000])
    return action

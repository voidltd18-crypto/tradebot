"""Fail-closed, persistent master trading pause. Not wired into live orders yet.

All automated order paths must consult this guard immediately before submitting.
A missing, unreadable, or corrupt state is PAUSED. The state must live on a
persistent volume (Render: /var/data), never in the ephemeral application tree.
"""
import json
import os
from pathlib import Path

DEFAULT_PATH = "/var/data/tradebot-master-pause.json"


def is_paused(path=None):
    """True on any uncertainty, including first boot and filesystem failure."""
    try:
        target = Path(path or os.environ.get("TRADEBOT_MASTER_PAUSE_PATH", DEFAULT_PATH))
        record = json.loads(target.read_text(encoding="utf-8"))
        return not (isinstance(record, dict)
                    and record.get("version") == 1
                    and record.get("paused") is False)
    except (OSError, ValueError, TypeError):
        return True


def may_submit_automatic_order(*, legacy_enabled, emergency_stop, manual_override, path=None):
    """Read on every order attempt, not once at process startup."""
    return (not is_paused(path)
            and legacy_enabled is True
            and emergency_stop is False
            and manual_override is False)

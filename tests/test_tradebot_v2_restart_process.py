"""Restart boundary tests: read-only subprocess integration on disposable Neon branch.

Never submits orders or modifies rows. Integration test runs only when the test
database URL is supplied and explicit opt-in is enabled.
"""
import json
import os
import subprocess
import sys

import pytest

from backend.tradebot_v2.durable_reservations import recover_active_offline


def test_restart_reader_requires_database():
    with pytest.raises(ValueError):
        recover_active_offline("")


@pytest.mark.skipif(
    not os.getenv("TRADEBOT_V2_TEST_DATABASE_URL")
    or os.getenv("TRADEBOT_V2_DISPOSABLE_TEST_BRANCH") != "true",
    reason="Requires explicitly opted-in disposable Neon test branch",
)
def test_recovery_consistent_across_fresh_processes():
    """Two fresh Python processes must recover identical durable active orders."""
    url = os.environ["TRADEBOT_V2_TEST_DATABASE_URL"]
    script = (
        "import json,sys;"
        "from backend.tradebot_v2.durable_reservations import recover_active_offline;"
        "print(json.dumps([(r.request_id,r.symbol,r.status) "
        "for r in recover_active_offline(sys.argv[1])]))"
    )
    def snapshot():
        completed = subprocess.run(
            [sys.executable, "-c", script, url],
            check=True, capture_output=True, text=True, timeout=20,
        )
        return json.loads(completed.stdout)
    first, second = snapshot(), snapshot()
    assert first == second
    assert isinstance(first, list)
    assert all(status in {"reserved", "submitted_unknown", "accepted", "partially_filled"}
               for _, _, status in first)

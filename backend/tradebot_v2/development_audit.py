"""Safe, non-trading development audit for an external scheduler.

Runs tests and prints a machine-readable result. This is NOT an autonomous
coding agent. No broker imports, order submission, deployments or commits.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKLOG = Path(__file__).with_name("development_backlog.json")
from development_coordinator import next_task


def main():
    backlog = json.loads(BACKLOG.read_text(encoding="utf-8"))
    if backlog.get("execution_enabled") is not False:
        raise SystemExit("Refusing audit: trading execution flag not disabled")
    tests = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "tests").glob("test_tradebot_v2_*.py"))
    if not tests:
        raise SystemExit("Refusing audit: no TradeBot v2 tests found")
    if os.getenv("TRADEBOT_V2_DISPOSABLE_TEST_BRANCH") == "true":
        # Test-only dependency: the isolated cron's build command installs pytest.
        # Fail closed if psycopg cannot be installed; never skip integration silently.
        install = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
             "psycopg[binary]==3.2.12"],
            cwd=ROOT, capture_output=True, text=True, timeout=90, check=False,
        )
        if install.returncode:
            raise SystemExit("Disposable Neon integration dependency installation failed")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", *tests],
            cwd=ROOT, capture_output=True, text=True, timeout=240, check=False,
        )
        code, output = result.returncode, (result.stdout + result.stderr)[-12000:]
    except subprocess.TimeoutExpired:
        code, output = 124, "Tests exceeded 240-second timeout"
    task = next_task(BACKLOG)
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "branch": backlog["branch"],
        "execution_enabled": False,
        "tests_exit_code": code,
        "test_files": len(tests),
        "next_task": task.task_id if task else None,
        "coding_agent_connected": False,
        "outstanding_tasks": [task["id"] for task in backlog["tasks"] if task["status"] != "verified"],
        "test_output": output,
    }
    print(json.dumps(report, indent=2))
    return 0 if code == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

import json
from pathlib import Path
import pytest
from backend.tradebot_v2.development_coordinator import next_task


def write(tmp_path, tasks, enabled=False):
    p = tmp_path / "backlog.json"
    p.write_text(json.dumps({"execution_enabled": enabled, "tasks": tasks}))
    return p


def test_picks_lowest_priority(tmp_path):
    p = write(tmp_path, [
        {"id": "later", "priority": 3, "status": "pending", "acceptance": "later"},
        {"id": "first", "priority": 1, "status": "pending", "acceptance": "first"}])
    assert next_task(p).task_id == "first"


def test_active_worker_blocks_new_work(tmp_path):
    p = write(tmp_path, [{"id": "one", "priority": 1, "status": "in_progress", "acceptance": "done"}])
    assert next_task(p) is None


def test_disables_trading_and_duplicate_ids(tmp_path):
    task = {"id": "one", "priority": 1, "status": "pending", "acceptance": "done"}
    with pytest.raises(ValueError):
        next_task(write(tmp_path, [task], enabled=True))
    with pytest.raises(ValueError):
        next_task(write(tmp_path, [task, task]))


def test_no_pending_tasks(tmp_path):
    assert next_task(write(tmp_path, [{"id": "done", "status": "verified"}])) is None

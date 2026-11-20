"""Offline development coordinator. No external coding agent is embedded.

The five-minute Render audit must not pretend to build code. This module
provides deterministic task selection for a separately authorised worker.
It never submits orders, edits files, deploys, or mutates databases.
"""
from dataclasses import dataclass
from pathlib import Path
import json


@dataclass(frozen=True)
class DevelopmentTask:
    task_id: str
    priority: int
    acceptance: str


def next_task(backlog_path: str | Path) -> DevelopmentTask | None:
    data = json.loads(Path(backlog_path).read_text(encoding="utf-8"))
    if data.get("execution_enabled") is not False:
        raise ValueError("Execution must remain disabled")
    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        raise ValueError("Invalid development backlog")
    pending = []
    seen = set()
    for task in tasks:
        if not isinstance(task, dict) or not isinstance(task.get("id"), str):
            raise ValueError("Invalid task")
        if task["id"] in seen:
            raise ValueError("Duplicate task identifier")
        seen.add(task["id"])
        if task.get("status") not in {"pending", "in_progress", "verified", "blocked"}:
            raise ValueError("Invalid task status")
        if task["status"] == "in_progress":
            # An in-progress task needs explicit recovery; never launch a second worker.
            return None
        if task["status"] == "pending":
            if not isinstance(task.get("priority"), int) or not isinstance(task.get("acceptance"), str):
                raise ValueError("Invalid task definition")
            pending.append(DevelopmentTask(task["id"], task["priority"], task["acceptance"]))
    return min(pending, key=lambda t: (t.priority, t.task_id)) if pending else None

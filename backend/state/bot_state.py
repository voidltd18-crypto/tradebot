from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, UTC
from threading import RLock
from typing import Any, Dict, List

@dataclass
class EngineState:
    name: str
    enabled: bool = False
    running: bool = False
    paused: bool = True
    dry_run: bool = True
    last_error: str = ''
    last_action: str = ''
    updated_at: str = ''
    scans: List[Dict[str, Any]] = field(default_factory=list)
    positions: List[Dict[str, Any]] = field(default_factory=list)
    trades: List[Dict[str, Any]] = field(default_factory=list)
    logs: List[str] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)

    def log(self, message: str):
        ts = datetime.now(UTC).strftime('%H:%M:%S')
        line = f'{ts} | {message}'
        self.logs.append(line)
        self.logs = self.logs[-200:]
        self.last_action = message
        self.updated_at = datetime.now(UTC).isoformat()
        print(f'[{self.name}] {line}')

class BotRegistry:
    def __init__(self):
        self.lock = RLock()
        self.engines: Dict[str, EngineState] = {}

    def add(self, name: str, state: EngineState):
        with self.lock:
            self.engines[name] = state

    def get(self, name: str) -> EngineState:
        with self.lock:
            return self.engines[name]

    def payload(self):
        with self.lock:
            return {name: state.__dict__ for name, state in self.engines.items()}

registry = BotRegistry()

from __future__ import annotations
import threading, time
from datetime import datetime, UTC, date
from typing import Dict, Any

class BaseEngine:
    def __init__(self, state, interval: int = 10):
        self.state = state
        self.interval = interval
        self.thread = None
        self.stop_event = threading.Event()

    def start(self):
        if self.thread and self.thread.is_alive():
            self.state.paused = False
            self.state.running = True
            self.state.log('resumed')
            return
        self.stop_event.clear()
        self.state.paused = False
        self.state.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        self.state.log('started')

    def pause(self):
        self.state.paused = True
        self.state.log('paused')

    def stop(self):
        self.stop_event.set()
        self.state.paused = True
        self.state.running = False
        self.state.log('stopped')

    def _loop(self):
        while not self.stop_event.is_set():
            try:
                if not self.state.paused:
                    self.tick()
            except Exception as e:
                self.state.last_error = str(e)
                self.state.log(f'ERROR {e}')
            time.sleep(self.interval)

    def tick(self):
        raise NotImplementedError

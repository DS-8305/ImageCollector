"""An active deadline shared by search, detail waits, and image downloads."""
from contextlib import contextmanager
import time


class ActiveBudget:
    def __init__(self, seconds):
        self.deadline = time.monotonic() + seconds
        self.paused_seconds = 0.0

    def remaining(self):
        return max(0.0, self.deadline - time.monotonic())

    @contextmanager
    def pause(self):
        start = time.monotonic()
        try:
            yield
        finally:
            elapsed = time.monotonic() - start
            self.deadline += elapsed
            self.paused_seconds += elapsed

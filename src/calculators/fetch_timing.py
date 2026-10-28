"""Per-fetch timing policy shared by API requests and graph retries."""

from dataclasses import dataclass
import math
import os
import time


class FetchBudgetExceeded(RuntimeError):
    """The fetch cannot continue within its configured time budget."""


@dataclass(frozen=True)
class FetchPolicy:
    connect_timeout: float = 10
    read_timeout: float = 180
    budget_seconds: float = 600
    max_attempts: int = 3
    retry_backoff: float = 10

    def __post_init__(self):
        for name in ('connect_timeout', 'read_timeout', 'budget_seconds', 'retry_backoff'):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f'Fairway Mapper {name} must be positive and finite')
        if self.read_timeout < 1:
            raise ValueError('Fairway Mapper read_timeout must be at least one second')
        if not isinstance(self.max_attempts, int) or self.max_attempts < 1:
            raise ValueError('Fairway Mapper max_attempts must be a positive integer')

    @classmethod
    def from_environment(cls):
        return cls(
            connect_timeout=float(os.environ.get('FAIRWAY_CONNECT_TIMEOUT_SECONDS', '10')),
            read_timeout=float(os.environ.get('FAIRWAY_READ_TIMEOUT_SECONDS', '180')),
            budget_seconds=float(os.environ.get('FAIRWAY_FETCH_BUDGET_SECONDS', '600')),
            max_attempts=int(os.environ.get('FAIRWAY_MAX_ATTEMPTS', '3')),
            retry_backoff=float(os.environ.get('FAIRWAY_RETRY_BACKOFF_SECONDS', '10')),
        )


class FetchBudget:
    """A cooperative deadline, not a hard cancellation of blocking operations."""

    def __init__(self, policy=None):
        self.policy = policy if policy is not None else FetchPolicy.from_environment()
        self.started = time.monotonic()

    def elapsed(self):
        return time.monotonic() - self.started

    def remaining(self):
        seconds = self.policy.budget_seconds - self.elapsed()
        if seconds <= 0:
            raise FetchBudgetExceeded(
                f'Fairway Mapper fetch exceeded its {self.policy.budget_seconds:g}s time budget'
            )
        return seconds

    def request_timeouts(self):
        remaining = self.remaining()
        connect = min(self.policy.connect_timeout, remaining / 2)
        return connect, min(self.policy.read_timeout, remaining - connect)

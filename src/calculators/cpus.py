"""How many CPUs intersection scoring may use."""

import math
import os


def available_cpus() -> int:
    """CPUs to score with: DEFAULT_CPU when it is set, otherwise what the OS reports.

    The function app that starts this container sizes it with its DEFAULT_CPU
    setting, so reading the same value keeps the number of scoring processes
    equal to the CPUs the container was given. Container Instances allows
    fractional CPUs (0.5, 1.5); those round down, never below 1.

    Raises ValueError for a DEFAULT_CPU that is not a positive number, rather
    than guessing a worker count.
    """
    raw = os.environ.get("DEFAULT_CPU", "").strip()
    if not raw:
        return os.cpu_count() or 1
    try:
        cpus = float(raw)
    except ValueError:
        raise ValueError(f"DEFAULT_CPU must be a number of CPUs, got {raw!r}") from None
    if not math.isfinite(cpus) or cpus <= 0:
        raise ValueError(f"DEFAULT_CPU must be a positive number of CPUs, got {raw!r}")
    return max(1, math.floor(cpus))

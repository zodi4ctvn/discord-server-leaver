"""General helpers: secure randomness, delays, retry timing and console logging."""

from __future__ import annotations

import os

from rich.console import Console

#: Shared console instance. ``print()`` is never used anywhere in the project.
console: Console = Console(highlight=False)


class GoBack(Exception):
    """Raised when the user presses Backspace / Esc to return to the previous step."""


# Layer 2 — adaptive human-like delay defaults (fast yet safe against rate limits).
DELAY_MIN: float = 0.8
DELAY_MAX: float = 2.0
REST_EVERY: int = 10
REST_MIN: float = 4.0
REST_MAX: float = 7.0

# Layer 1 — jitter added after a header-announced reset.
HEADER_RESET_JITTER: float = 0.1


def secure_uniform(low: float, high: float) -> float:
    """Return a float uniformly distributed in ``[low, high]``.

    Entropy is drawn directly from :func:`os.urandom` (not the ``random`` module),
    so the delay pattern cannot be predicted from a PRNG seed.
    """
    if high < low:
        low, high = high, low
    fraction = int.from_bytes(os.urandom(8), "big") / float(1 << 64)
    return low + (high - low) * fraction


def human_delay() -> float:
    """Return a random inter-request delay in seconds (``0.8–2.0s``)."""
    return secure_uniform(DELAY_MIN, DELAY_MAX)


def rest_delay() -> float:
    """Return a random longer rest in seconds (``4.0–7.0s``), used every 10 leaves."""
    return secure_uniform(REST_MIN, REST_MAX)


def next_delay(completed: int, total: int) -> float:
    """Return the human-like delay that should follow the ``completed``-th leave request.

    No delay is applied after the final request. After every ``REST_EVERY`` requests an
    additional rest period (``4.0–7.0s``) is added.

    Args:
        completed: Number of leave requests already performed (1-based).
        total: Total number of leave requests planned.
    """
    if completed >= total:
        return 0.0
    delay = human_delay()
    if completed % REST_EVERY == 0:
        delay += rest_delay()
    return delay


def estimate_seconds(count: int) -> float:
    """Estimate the total run time in seconds for leaving ``count`` servers.

    Uses the mean of the human delay and rest ranges; request latency is ignored.
    """
    if count <= 0:
        return 0.0
    mean_delay = (DELAY_MIN + DELAY_MAX) / 2
    mean_rest = (REST_MIN + REST_MAX) / 2
    gaps = count - 1
    rests = gaps // REST_EVERY
    return gaps * mean_delay + rests * mean_rest


def format_duration(seconds: float) -> str:
    """Format a duration as a short human-readable string (e.g. ``45s`` or ``3m 12s``)."""
    seconds = max(0.0, seconds)
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes, secs = divmod(int(round(seconds)), 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def backoff_429(retry_after: float, attempt: int) -> float:
    """Compute the 429 backoff: ``retry_after * 1.5 ** attempt`` plus a small jitter.

    Args:
        retry_after: The ``retry_after`` value (seconds) reported by Discord.
        attempt: Zero-based retry attempt number.
    """
    base = max(retry_after, 0.5)
    return base * (1.5**attempt) + secure_uniform(0.0, HEADER_RESET_JITTER)


def log_info(message: str) -> None:
    """Log an informational message to the console."""
    console.print(f"[cyan]•[/cyan] {message}")


def log_warning(message: str) -> None:
    """Log a warning message to the console."""
    console.print(f"[yellow]![/yellow] {message}")


def log_error(message: str) -> None:
    """Log an error message to the console."""
    console.print(f"[red]×[/red] {message}")

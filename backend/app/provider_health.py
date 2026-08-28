"""Remembering which data providers are currently out of quota.

Without this, an exhausted provider is retried on every single lookup: each
one waits for a network round trip, gets the same refusal, and only then falls
through to the next provider. Fifty tickers means fifty wasted requests and
fifty delays, all to relearn something the first one already established.

So a refusal is remembered. A provider that says it is rate limited is skipped
until its cooldown expires -- long for a daily quota, short for a per-minute
one, because those recover on their own in a moment. Anything else counts as a
blip and is not held against it: a single flaky response should not take a
working provider out of rotation.

Held in memory rather than the database on purpose. It is a hint, not a fact,
and a restart rediscovering it costs one request.
"""

import time
from dataclasses import dataclass

# A daily allowance is gone until the provider's clock rolls over, and nothing
# is learned by asking again in the meantime.
DAILY_COOLDOWN_SECONDS = 60 * 60
# A per-minute cap recovers on its own almost immediately.
BURST_COOLDOWN_SECONDS = 90

DAILY_HINTS = ("per day", "daily", "/day", "day)", "quota")
# Providers word this differently: "rate limit reached", "too many requests",
# "exceeded the daily hits limit". All of them mean the same thing, and one
# that is not recognised here is retried on every single lookup.
LIMIT_HINTS = (
    "rate limit",
    "rate-limit",
    "ratelimit",
    "too many requests",
    "429",
    "quota",
    "exceeded",
    "limit reached",
)


@dataclass
class ProviderState:
    name: str
    cooldown_until: float = 0.0
    reason: str = ""
    failures: int = 0
    successes: int = 0
    last_error: str = ""


_states: dict[str, ProviderState] = {}


def _now() -> float:
    return time.monotonic()


def state(name: str) -> ProviderState:
    return _states.setdefault(name, ProviderState(name=name))


def reset() -> None:
    """Forget everything. Tests need a clean slate between cases."""
    _states.clear()


def looks_rate_limited(message: str) -> bool:
    text = (message or "").lower()
    return any(hint in text for hint in LIMIT_HINTS)


def cooldown_for(message: str) -> int:
    """How long to leave a provider alone, judged by what it said."""
    text = (message or "").lower()
    if any(hint in text for hint in DAILY_HINTS):
        return DAILY_COOLDOWN_SECONDS
    return BURST_COOLDOWN_SECONDS


def is_available(name: str) -> bool:
    return _now() >= state(name).cooldown_until


def record_success(name: str) -> None:
    entry = state(name)
    entry.successes += 1
    # A provider that answers is back, whatever it said last time.
    entry.cooldown_until = 0.0
    entry.reason = ""


def record_failure(name: str, message: str) -> None:
    """Note a failure, and bench the provider if it was a quota refusal."""
    entry = state(name)
    entry.failures += 1
    entry.last_error = message

    if looks_rate_limited(message):
        seconds = cooldown_for(message)
        entry.cooldown_until = _now() + seconds
        entry.reason = message


def seconds_remaining(name: str) -> int:
    return max(0, int(round(state(name).cooldown_until - _now())))


def snapshot(names: list[str]) -> list[dict]:
    """Readable status for every provider, for the diagnostics endpoint."""
    return [
        {
            "name": name,
            "available": is_available(name),
            "cooldown_seconds": seconds_remaining(name),
            "reason": state(name).reason or None,
            "successes": state(name).successes,
            "failures": state(name).failures,
            "last_error": state(name).last_error or None,
        }
        for name in names
    ]

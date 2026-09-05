"""Shared provider results and single-flight requests, not account data.

The database cache survives restarts when DATABASE_URL is persistent. Locks
coalesce concurrent requests within a worker; workers share the stored results.
Never cache errors or empty responses, and never extend a result's timestamp
on a cache hit. Refreshing the UI still respects these upstream safety windows.
"""
import asyncio
import hashlib
import json
from weakref import WeakValueDictionary

from app import db

_locks: WeakValueDictionary = WeakValueDictionary()


def lock_for(key: str) -> asyncio.Lock:
    lock = _locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _locks[key] = lock
    return lock


async def cached_call(operation: str, arguments, ttl: int, fetch):
    digest = hashlib.sha256(json.dumps(arguments, sort_keys=True).encode()).hexdigest()
    key = f"upstream:v1:{operation}:{digest}"
    async with lock_for(key):
        cached = db.get_market_cache(key, ttl)
        if cached is not None:
            return cached
        result = await fetch()
        if result:
            db.set_market_cache(key, result)
        return result

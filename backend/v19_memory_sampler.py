"""V19 read-only process and collection memory sampler.

No imports from the trading application. Caller passes the collections explicitly.
Does not traverse, mutate, persist or serialise their contents.
"""
import gc
import os
from collections.abc import Mapping, Sized


def process_rss_mb():
    """Linux RSS from procfs; None on platforms without procfs."""
    try:
        with open("/proc/self/status", encoding="utf-8") as stream:
            for line in stream:
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024.0, 2)
    except (OSError, ValueError, IndexError):
        pass
    return None


def sample_collections(collections):
    """Count top-level entries only; never inspect trading records."""
    if not isinstance(collections, Mapping):
        raise TypeError("collections must be a mapping")
    sizes = {}
    for name, value in collections.items():
        if not isinstance(name, str):
            raise TypeError("collection names must be strings")
        sizes[name] = len(value) if isinstance(value, Sized) else None
    return {
        "rss_mb": process_rss_mb(),
        "gc_generations": tuple(gc.get_count()),
        "collection_lengths": sizes,
    }


def compare_samples(before, after):
    """Return measured RSS and top-level collection growth, if available."""
    first, last = before.get("rss_mb"), after.get("rss_mb")
    keys = before["collection_lengths"].keys() & after["collection_lengths"].keys()
    return {
        "rss_delta_mb": round(last - first, 2) if first is not None and last is not None else None,
        "collection_deltas": {
            key: after["collection_lengths"][key] - before["collection_lengths"][key]
            for key in keys
            if before["collection_lengths"][key] is not None and after["collection_lengths"][key] is not None
        },
    }

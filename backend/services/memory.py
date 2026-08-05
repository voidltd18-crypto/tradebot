"""V13 autonomous long-term memory service boundary.

The live implementation remains compatibility-hosted in backend.legacy.monolith
while exposing stable /v13/memory interfaces for later extraction.
"""
from .registry import SERVICE_REGISTRY
DESCRIPTOR = next(item for item in SERVICE_REGISTRY if item.key == "memory")
__all__ = ["DESCRIPTOR"]

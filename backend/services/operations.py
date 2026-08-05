"""V15 autonomous AI Operations Centre service boundary.

The compatibility implementation remains in backend.legacy.monolith while this
module provides a stable extraction point for later modular migration.
"""
from .registry import SERVICE_REGISTRY

DESCRIPTOR = next((item for item in SERVICE_REGISTRY if item.key == "operations"), None)
__all__ = ["DESCRIPTOR"]

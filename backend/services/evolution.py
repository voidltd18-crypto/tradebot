"""Evolution service boundary.

V12.2 compatibility phase: live implementation remains in
backend.legacy.monolith. This module is the permanent extraction target
for the evolution subsystem and deliberately contains no duplicated runtime logic.
"""
from .registry import SERVICE_REGISTRY

DESCRIPTOR = next(item for item in SERVICE_REGISTRY if item.key == "evolution")

__all__ = ["DESCRIPTOR"]

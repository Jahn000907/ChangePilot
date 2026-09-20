"""Deterministic ChangePilot business rules.

Every module in this package is pure: it takes structured DTOs, returns
structured DTOs, never touches a database and never reads the system clock.
Business dates are always passed in explicitly.
"""

from __future__ import annotations

__all__ = ["impact"]

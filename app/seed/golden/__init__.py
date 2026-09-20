"""ChangePilot Golden Seed package.

The golden seed is the hand-maintained, deterministic data set of the simulated
company: product structure in Neo4j, ERP facts in PostgreSQL. See ``data.py``
for the definitions, ``neo4j.py`` / ``postgres.py`` for the loaders and
``validation.py`` for the verification suite.
"""

from __future__ import annotations

__all__ = ["data", "neo4j", "postgres", "validation"]

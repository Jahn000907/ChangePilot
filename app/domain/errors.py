"""ChangePilot domain errors module.

The hierarchy follows design doc v0.4 section 21. Two thin subclasses are added
so callers can distinguish the product structure failures from a generic
"not found" without inspecting message text:

- :class:`PartRevisionNotFoundError` — the requested part / revision is missing;
- :class:`BomNotFoundError` — the revision exists but has no BOM version in the
  requested state;
- :class:`DepthLimitExceededError` — the graph is deeper than ``max_depth``.

Upper layers only ever see these exceptions; no database driver exception is
allowed to escape the repository / service boundary.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for every ChangePilot domain error."""


class DomainValidationError(DomainError):
    """A value violates a domain rule (for example ``max_depth <= 0``)."""


class EntityNotFoundError(DomainError):
    """A requested domain object does not exist."""


class PartRevisionNotFoundError(EntityNotFoundError):
    """The requested ``(part_number, revision_code)`` does not exist."""


class BomNotFoundError(EntityNotFoundError):
    """The part revision exists but holds no BOM version in the asked states."""


class DepthLimitExceededError(DomainValidationError):
    """The traversal was truncated because the graph is deeper than ``max_depth``."""


class ConflictError(DomainError):
    """The operation conflicts with the current state of the data."""


class NoEffectiveBOMError(EntityNotFoundError):
    """No RELEASED BOM version is effective on the requested business date."""


class AmbiguousEffectiveBOMError(ConflictError):
    """More than one RELEASED BOM version is effective on the same date.

    v0.4 section 15 (BOM-03) allows at most one effective RELEASED BOM per part
    revision and date, so this is a data conflict, never something to silently
    resolve by picking one row.
    """


class PermissionDeniedError(DomainError):
    """The caller is not allowed to perform the operation."""


class ApprovalRequiredError(DomainError):
    """A human approval is required before the operation may proceed."""


class IdempotencyConflictError(DomainError):
    """The same idempotency key was used with a different request."""


class ExternalToolError(DomainError):
    """An external system (PLM / ERP / tool) failed."""


class ExecutionFailedError(DomainError):
    """A controlled execution job failed."""

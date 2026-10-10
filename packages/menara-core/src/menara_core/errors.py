"""Errors raised by Menara tools. MCP clients see the message as the tool error."""

from __future__ import annotations


class MenaraError(Exception):
    """Base class for all expected tool errors."""


class NotFoundError(MenaraError):
    """The requested object does not exist in the synthetic dataset."""


class InvalidInputError(MenaraError):
    """The caller passed a malformed or out-of-range argument."""


class TokenError(MenaraError):
    """A policy token is missing, forged, expired, or issued for another action."""


class PermissionDeniedError(MenaraError):
    """The caller lacks the credential this action needs (for example the human approver key)."""


class SourceUnavailableError(MenaraError):
    """A real upstream data source timed out, failed, or returned something unexpected."""


class DatabaseNotSeededError(MenaraError):
    """The SQLite file is missing; run `uv run menara-seed` first."""
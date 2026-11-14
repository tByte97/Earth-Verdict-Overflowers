"""Exceptions raised by external data source adapters."""
from __future__ import annotations


class SourceUnavailable(Exception):
    """Raised when an external data source fails or is unavailable offline."""

    def __init__(self, source: str, message: str) -> None:
        self.source = source
        self.message = message
        super().__init__(f"{source}: {message}")

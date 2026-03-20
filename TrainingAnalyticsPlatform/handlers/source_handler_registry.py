"""Source handler registry contracts for queue operation dispatch."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generic, Optional, TypeVar

AsyncIngestionSourceHandler = Callable[[str, int, bool], Dict[str, Any]]
DeferredRetrySourceHandler = Callable[[str, int], tuple[Dict[str, Any], int] | tuple[Dict[str, Any], int, Dict[str, Any]]]

HandlerType = TypeVar("HandlerType")


@dataclass(frozen=True)
class SourceHandlerRegistry(Generic[HandlerType]):
    """Registry mapping source identifiers to handler callables."""

    handlers: Dict[str, HandlerType] = field(default_factory=dict)

    def resolve(self, source: str) -> Optional[HandlerType]:
        """Resolve a source identifier to a registered handler."""
        return self.handlers.get(source)

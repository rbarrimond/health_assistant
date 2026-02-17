"""Type definitions for handlers."""

from typing import Any, Dict, List, Tuple, TypeAlias, Union

# Handler response patterns
HandlerResponse: TypeAlias = Tuple[Dict[str, Any], int]
HandlerListResponse: TypeAlias = Tuple[List[Dict[str, Any]], int]
HandlerStringResponse: TypeAlias = Tuple[str, int]

# Common response bodies
SuccessResponse: TypeAlias = Dict[str, Any]
ErrorResponse: TypeAlias = Dict[str, Union[str, Dict]]

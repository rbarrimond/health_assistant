"""Type definitions for handlers."""  # pragma: no cover

from typing import Any, Dict, List, Tuple, TypeAlias, Union

# Handler response patterns
HandlerResponse: TypeAlias = Tuple[Dict[str, Any], int]  # pragma: no cover
HandlerListResponse: TypeAlias = Tuple[List[Dict[str, Any]], int]  # pragma: no cover
HandlerStringResponse: TypeAlias = Tuple[str, int]  # pragma: no cover

# Common response bodies
SuccessResponse: TypeAlias = Dict[str, Any]  # pragma: no cover
ErrorResponse: TypeAlias = Dict[str, Union[str, Dict]]  # pragma: no cover

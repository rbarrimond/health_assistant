"""Policy tests for explicit exception chaining in business logic."""

from __future__ import annotations

import ast
from pathlib import Path


def _business_logic_files() -> list[Path]:
    files = [Path("function_app.py"), Path("utils.py")]
    files.extend(Path("TrainingAnalyticsPlatform").rglob("*.py"))
    return [path for path in files if path.exists()]


def _iter_try_nodes(tree: ast.AST) -> list[ast.Try]:
    return [node for node in ast.walk(tree) if isinstance(node, ast.Try)]


def _iter_named_handlers(try_node: ast.Try) -> list[tuple[str, ast.ExceptHandler]]:
    named_handlers: list[tuple[str, ast.ExceptHandler]] = []
    for handler in try_node.handlers:
        if isinstance(handler.name, str):
            named_handlers.append((handler.name, handler))
    return named_handlers


def _is_unwrapped_new_raise(raise_node: ast.Raise, caught_name: str) -> bool:
    if raise_node.exc is None:
        return False
    if raise_node.cause is not None:
        return False

    is_bare_reraise = (
        isinstance(raise_node.exc, ast.Name)
        and raise_node.exc.id == caught_name
    )
    return not is_bare_reraise


def _render_exc_expression(exc_node: ast.AST) -> str:
    if hasattr(ast, "unparse"):
        return ast.unparse(exc_node)
    return type(exc_node).__name__


def _find_unwrapped_in_handler(
    caught_name: str,
    handler: ast.ExceptHandler,
) -> list[tuple[int, str, str]]:
    violations: list[tuple[int, str, str]] = []
    handler_module = ast.Module(body=handler.body, type_ignores=[])
    for raise_node in ast.walk(handler_module):
        if not isinstance(raise_node, ast.Raise):
            continue
        if not _is_unwrapped_new_raise(raise_node, caught_name):
            continue
        if raise_node.exc is None:
            continue
        rendered = _render_exc_expression(raise_node.exc)
        violations.append((raise_node.lineno, caught_name, rendered))
    return violations


def _find_unwrapped_reraises(path: Path) -> list[tuple[int, str, str]]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    violations: list[tuple[int, str, str]] = []
    for try_node in _iter_try_nodes(tree):
        for caught_name, handler in _iter_named_handlers(try_node):
            violations.extend(_find_unwrapped_in_handler(caught_name, handler))

    return violations


def test_business_logic_wraps_exceptions_with_explicit_cause() -> None:
    """All wrapped exceptions should use `raise ... from exc` in business logic."""
    failures: list[str] = []

    for path in _business_logic_files():
        for lineno, caught_name, rendered in _find_unwrapped_reraises(path):
            failures.append(
                f"{path.as_posix()}:{lineno} except {caught_name} -> raise {rendered} (missing `from {caught_name}`)"
            )

    assert not failures, "\n".join(failures)

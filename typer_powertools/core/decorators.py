"""
High-level composite decorators that bundle multiple powertools together.

These helpers encode the recommended decorator stacking order from QUICKREF:

    @app.command()
    @audit_command(...)
    @cached_command(...)
    @hooks.wrap
    @use_middleware([...])
    @config_option(...)
    @progress_command(...)

So you can enable a full stack of behavior with a single decorator.
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional, TypeVar

from typer_powertools.config.loader import config_option
from typer_powertools.input.progress import progress_command
from typer_powertools.lifecycle.cache import cached_command
from typer_powertools.lifecycle.hooks import wrap_command
from typer_powertools.observability.audit import audit_command
from typer_powertools.observability.middleware import MiddlewareFunc, use_middleware

F = TypeVar("F", bound=Callable[..., Any])


def full_stack_command(
    app_name: str,
    *,
    cache_ttl: int = 300,
    sensitive_params: Optional[List[str]] = None,
    middleware: Optional[List[MiddlewareFunc]] = None,
    progress_description: str = "Working…",
) -> Callable[[F], F]:
    """Bundle audit + cache + hooks + middleware + config + progress in one decorator.

    Parameters
    ----------
    app_name:
        Application name, used by audit/cache/config to resolve defaults.
    cache_ttl:
        TTL (seconds) for :func:`cached_command`.
    sensitive_params:
        List of parameter names to redact in audit logs.
    middleware:
        Optional list of middleware callables to apply via :func:`use_middleware`.
    progress_description:
        Description string for :func:`progress_command`.
    """

    def decorator(func: F) -> F:
        wrapped: F = func

        # Innermost to outermost — apply in reverse of call order
        wrapped = progress_command(description=progress_description)(wrapped)
        wrapped = config_option(app_name=app_name)(wrapped)
        if middleware:
            wrapped = use_middleware(middleware)(wrapped)
        wrapped = wrap_command(wrapped)
        wrapped = cached_command(ttl=cache_ttl, app_name=app_name)(wrapped)
        wrapped = audit_command(app_name=app_name, sensitive_params=sensitive_params)(wrapped)

        return wrapped

    return decorator

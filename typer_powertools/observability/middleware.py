"""
Django/Express-style middleware pipeline for CLI commands.

Middleware functions can:
  • Inspect/modify arguments before command execution
  • Transform command results
  • Short-circuit execution
  • Handle errors

Usage
-----
    from typer_powertools.observability.middleware import use_middleware, Middleware
    import typer

    app = typer.Typer()

    def check_auth(next_fn, *args, **kwargs):
        if not is_authenticated():
            raise typer.Exit(code=1)
        return next_fn(*args, **kwargs)

    def rate_limit(next_fn, *args, **kwargs):
        if exceeded_rate_limit():
            typer.echo("Rate limit exceeded")
            raise typer.Exit(code=429)
        return next_fn(*args, **kwargs)

    @app.command()
    @use_middleware([check_auth, rate_limit])
    def deploy(env: str):
        do_deploy(env)
"""

from __future__ import annotations

import functools
import time
from typing import Any, Callable, Dict, List, Optional, TypeVar

import typer
from rich.console import Console

console = Console()
F = TypeVar("F", bound=Callable[..., Any])

# Type alias for middleware functions
MiddlewareFunc = Callable[[Callable[..., Any], Any, Any], Any]


class MiddlewarePipeline:
    """Manages a chain of middleware functions."""

    def __init__(self, middlewares: Optional[List[MiddlewareFunc]] = None) -> None:
        """
        Parameters
        ----------
        middlewares:
            List of middleware functions. Each receives (next_fn, *args, **kwargs).
        """
        self.middlewares = middlewares or []

    def add(self, middleware: MiddlewareFunc) -> None:
        """Add a middleware to the pipeline."""
        self.middlewares.append(middleware)

    def wrap(self, func: F) -> F:
        """Wrap a function with the middleware pipeline."""

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Build the chain from innermost to outermost
            final_func = func

            for middleware in reversed(self.middlewares):

                def make_next(
                    mw: MiddlewareFunc, next_fn: Callable[..., Any]
                ) -> Callable[..., Any]:
                    return lambda *a, **kw: mw(next_fn, *a, **kw)

                final_func = make_next(middleware, final_func)

            return final_func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]


def use_middleware(middlewares: List[MiddlewareFunc]) -> Callable[[F], F]:
    """Decorator that applies a list of middleware to a command.

    Parameters
    ----------
    middlewares:
        List of middleware functions. Each middleware receives:
            - next_fn: The next function in the chain
            - *args: Positional arguments
            - **kwargs: Keyword arguments

    Example
    -------
    ::

        @app.command()
        @use_middleware([auth_check, rate_limit, logging])
        def deploy(env: str):
            do_deploy(env)
    """
    pipeline = MiddlewarePipeline(middlewares)

    def decorator(func: F) -> F:
        return pipeline.wrap(func)

    return decorator


def timing_middleware(
    threshold_ms: float = 1000.0,
    verbose: bool = True,
) -> MiddlewareFunc:
    """Middleware that logs execution time for slow commands.

    Parameters
    ----------
    threshold_ms:
        Only log if execution exceeds this threshold (milliseconds).
    verbose:
        Always log timing, regardless of threshold.
    """

    def middleware(next_fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        result = next_fn(*args, **kwargs)
        duration_ms = (time.perf_counter() - start) * 1000

        if verbose or duration_ms > threshold_ms:
            console.print(f"[dim]⏱ {duration_ms:.1f}ms[/dim]")

        return result

    return middleware


def retry_middleware(
    max_retries: int = 3,
    delay: float = 1.0,
    exponential_backoff: bool = True,
) -> MiddlewareFunc:
    """Middleware that retries failed commands.

    Parameters
    ----------
    max_retries:
        Maximum number of retry attempts.
    delay:
        Initial delay between retries (seconds).
    exponential_backoff:
        If *True*, delay doubles after each retry.
    """

    def middleware(next_fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        last_exception = None
        current_delay = delay

        for attempt in range(max_retries + 1):
            try:
                return next_fn(*args, **kwargs)
            except Exception as exc:
                last_exception = exc
                if attempt < max_retries:
                    console.print(
                        f"[yellow]⚠ Attempt {attempt + 1}/{max_retries + 1} failed. "
                        f"Retrying in {current_delay:.1f}s…[/yellow]"
                    )
                    time.sleep(current_delay)
                    if exponential_backoff:
                        current_delay *= 2

        # All retries exhausted
        console.print(f"[red]✗ All {max_retries + 1} attempts failed.[/red]")
        raise last_exception  # type: ignore[misc]

    return middleware


def logging_middleware(
    log_args: bool = True,
    log_result: bool = False,
) -> MiddlewareFunc:
    """Middleware that logs command invocations.

    Parameters
    ----------
    log_args:
        Log function arguments.
    log_result:
        Log function return value.
    """

    def middleware(next_fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        cmd_name = next_fn.__name__

        if log_args:
            console.print(f"[dim]→ {cmd_name}({args}, {kwargs})[/dim]")
        else:
            console.print(f"[dim]→ {cmd_name}()[/dim]")

        result = next_fn(*args, **kwargs)

        if log_result:
            console.print(f"[dim]← {cmd_name}() = {result!r}[/dim]")

        return result

    return middleware


def validate_middleware(
    validator: Callable[[Dict[str, Any]], Optional[str]],
) -> MiddlewareFunc:
    """Middleware that validates arguments before execution.

    Parameters
    ----------
    validator:
        Function that receives kwargs dict and returns error message or *None*.

    Example
    -------
    ::

        def check_env(kwargs):
            if kwargs.get("env") not in ["staging", "production"]:
                return "Invalid env: must be staging or production"
            return None

        @use_middleware([validate_middleware(check_env)])
        def deploy(env: str):
            ...
    """

    def middleware(next_fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        error = validator(kwargs)
        if error:
            console.print(f"[red]✗ Validation failed: {error}[/red]")
            raise typer.Exit(code=1)
        return next_fn(*args, **kwargs)

    return middleware


def require_confirmation_middleware(
    message: str = "Continue?",
    abort_message: str = "Aborted.",
) -> MiddlewareFunc:
    """Middleware that requires user confirmation before proceeding.

    Parameters
    ----------
    message:
        Confirmation prompt message.
    abort_message:
        Message shown when user declines.
    """

    def middleware(next_fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        confirmed = typer.confirm(message)
        if not confirmed:
            console.print(f"[yellow]{abort_message}[/yellow]")
            raise typer.Abort()
        return next_fn(*args, **kwargs)

    return middleware


def dry_run_middleware(
    dry_run_param: str = "dry_run",
) -> MiddlewareFunc:
    """Middleware that intercepts execution when --dry-run flag is set.

    Parameters
    ----------
    dry_run_param:
        Name of the boolean parameter that indicates dry-run mode.

    Example
    -------
    ::

        @app.command()
        @use_middleware([dry_run_middleware()])
        def deploy(env: str, dry_run: bool = False):
            # This only runs if dry_run is False
            do_deploy(env)
    """

    def middleware(next_fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if kwargs.get(dry_run_param, False):
            console.print("[yellow]DRY RUN — command not executed[/yellow]")
            return None
        return next_fn(*args, **kwargs)

    return middleware


class Middleware:
    """Base class for class-based middleware.

    Subclass and override :meth:`process` to implement custom logic.

    Example
    -------
    ::

        class AuthMiddleware(Middleware):
            def process(self, next_fn, *args, **kwargs):
                if not self.check_token():
                    raise typer.Exit(code=1)
                return next_fn(*args, **kwargs)

            def check_token(self):
                return os.getenv("TOKEN") is not None
    """

    def process(self, next_fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Override this method in subclasses.

        Parameters
        ----------
        next_fn:
            The next function in the middleware chain.
        *args, **kwargs:
            Arguments passed to the command.

        Returns
        -------
        any
            The result from calling next_fn or a short-circuit value.
        """
        return next_fn(*args, **kwargs)

    def __call__(self, next_fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Make the middleware callable."""
        return self.process(next_fn, *args, **kwargs)


class GlobalMiddlewareRegistry:
    """Registry for middleware that applies to all commands."""

    def __init__(self) -> None:
        self.middlewares: List[MiddlewareFunc] = []

    def register(self, middleware: MiddlewareFunc) -> None:
        """Register a middleware globally."""
        self.middlewares.append(middleware)

    def wrap_app(self, app: typer.Typer) -> None:
        """Apply registered middleware to all commands in the app."""
        pipeline = MiddlewarePipeline(self.middlewares)
        for cmd in app.registered_commands:  # type: ignore[attr-defined]
            if cmd.callback:
                original = cmd.callback
                cmd.callback = pipeline.wrap(original)


# Singleton registry
_global_registry = GlobalMiddlewareRegistry()


def reset_global_registry() -> None:
    """Reset the global middleware registry (useful for testing or app isolation)."""
    global _global_registry
    _global_registry = GlobalMiddlewareRegistry()


def register_global_middleware(middleware: MiddlewareFunc) -> None:
    """Register middleware to apply to all commands."""
    _global_registry.register(middleware)


def apply_global_middleware(app: typer.Typer) -> None:
    """Apply all globally registered middleware to an app."""
    _global_registry.wrap_app(app)

"""
Pre/Post command execution hooks for setup, teardown, and error handling.

Execute code before/after any command runs, or handle errors globally.

Usage
-----
    from typer_powertools.lifecycle.hooks import HookManager, on_before, on_after, on_error
    import typer

    hooks = HookManager()

    @hooks.before
    def setup():
        print("Setting up...")

    @hooks.after
    def cleanup():
        print("Cleaning up...")

    @hooks.error
    def handle_error(exc):
        print(f"Error: {exc}")

    app = typer.Typer()

    @app.command()
    @hooks.wrap
    def deploy():
        # setup runs before this
        do_deploy()
        # cleanup runs after this
        # handle_error runs if exception occurs

    # Or use global registration:
    hooks.register_global(app)  # wraps ALL commands automatically
"""

from __future__ import annotations

import functools
from typing import Any, Callable, Dict, List, TypeVar

import typer
from rich.console import Console

console = Console()
F = TypeVar("F", bound=Callable[..., Any])


class HookManager:
    def __init__(self) -> None:
        """Initialize an empty hook manager with four hook lists (before, after, error, finally)."""
        self._before_hooks: List[Callable[[], None]] = []
        self._after_hooks: List[Callable[[], None]] = []
        self._error_hooks: List[Callable[[Exception], None]] = []
        self._finally_hooks: List[Callable[[], None]] = []

    def before(self, func: Callable[[], None]) -> Callable[[], None]:
        """Register a function to run before every wrapped command."""
        self._before_hooks.append(func)
        return func

    def after(self, func: Callable[[], None]) -> Callable[[], None]:
        """Register a function to run after every wrapped command (success only)."""
        self._after_hooks.append(func)
        return func

    def error(self, func: Callable[[Exception], None]) -> Callable[[Exception], None]:
        """Register a function to handle exceptions from wrapped commands."""
        self._error_hooks.append(func)
        return func

    def finally_hook(self, func: Callable[[], None]) -> Callable[[], None]:
        """Register a function to run after every wrapped command (always)."""
        self._finally_hooks.append(func)
        return func

    def wrap(self, func: F) -> F:
        """Decorator that wraps a Typer command with registered hooks."""

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Run before hooks
            for hook in self._before_hooks:
                try:
                    hook()
                except Exception as exc:
                    console.print(f"[yellow]⚠ before hook failed: {exc}[/yellow]")

            result = None
            exception_occurred = False

            try:
                result = func(*args, **kwargs)
                return result
            except Exception as exc:
                exception_occurred = True
                # Run error hooks
                for hook in self._error_hooks:
                    try:
                        hook(exc)
                    except Exception as hook_exc:
                        console.print(f"[yellow]⚠ error hook failed: {hook_exc}[/yellow]")
                raise
            finally:
                # Run after hooks (only on success)
                if not exception_occurred:
                    for hook in self._after_hooks:
                        try:
                            hook()
                        except Exception as exc:
                            console.print(f"[yellow]⚠ after hook failed: {exc}[/yellow]")

                # Run finally hooks (always)
                for hook in self._finally_hooks:
                    try:
                        hook()
                    except Exception as exc:
                        console.print(f"[yellow]⚠ finally hook failed: {exc}[/yellow]")

        return wrapper  # type: ignore[return-value]

    def register_global(self, app: typer.Typer) -> None:
        """Wrap ALL commands in the Typer app with hooks automatically."""
        # We need to wrap each registered command's callback
        for cmd in app.registered_commands:  # type: ignore[attr-defined]
            if cmd.callback:
                original = cmd.callback
                cmd.callback = self.wrap(original)


_default_manager = HookManager()


def reset_default_manager() -> None:
    """Reset the global default hook manager (useful for testing or app isolation)."""
    global _default_manager
    _default_manager = HookManager()


def on_before(func: Callable[[], None]) -> Callable[[], None]:
    """Decorator to register a before hook on the default manager."""
    return _default_manager.before(func)


def on_after(func: Callable[[], None]) -> Callable[[], None]:
    """Decorator to register an after hook on the default manager."""
    return _default_manager.after(func)


def on_error(func: Callable[[Exception], None]) -> Callable[[Exception], None]:
    """Decorator to register an error hook on the default manager."""
    return _default_manager.error(func)


def on_finally(func: Callable[[], None]) -> Callable[[], None]:
    """Decorator to register a finally hook on the default manager."""
    return _default_manager.finally_hook(func)


def wrap_command(func: F) -> F:
    """Wrap a command with the default hook manager."""
    return _default_manager.wrap(func)


def register_global_hooks(app: typer.Typer) -> None:
    """Register hooks globally on all commands in the app."""
    _default_manager.register_global(app)


class ContextHookManager(HookManager):
    def __init__(self) -> None:
        """Extend HookManager with context-aware hooks that receive command name and args."""
        super().__init__()
        self._before_ctx_hooks: List[Callable[[Dict[str, Any]], None]] = []
        self._after_ctx_hooks: List[Callable[[Dict[str, Any], Any], None]] = []

    def before_with_context(
        self, func: Callable[[Dict[str, Any]], None]
    ) -> Callable[[Dict[str, Any]], None]:
        """Register a before hook that receives the command context dict."""
        self._before_ctx_hooks.append(func)
        return func

    def after_with_context(
        self, func: Callable[[Dict[str, Any], Any], None]
    ) -> Callable[[Dict[str, Any], Any], None]:
        """Register an after hook that receives the context dict and the command result."""
        self._after_ctx_hooks.append(func)
        return func

    def wrap(self, func: F) -> F:
        """Wrap a command with both standard and context-aware hooks."""

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            context = {
                "command_name": func.__name__,
                "args": args,
                "kwargs": kwargs,
            }

            # Standard before hooks
            for hook in self._before_hooks:
                try:
                    hook()
                except Exception as exc:
                    console.print(f"[yellow]⚠ before hook: {exc}[/yellow]")

            # Context-aware before hooks
            for hook in self._before_ctx_hooks:
                try:
                    hook(context)
                except Exception as exc:
                    console.print(f"[yellow]⚠ before context hook: {exc}[/yellow]")

            result = None
            exception_occurred = False

            try:
                result = func(*args, **kwargs)
                return result
            except Exception as exc:
                exception_occurred = True
                for hook in self._error_hooks:
                    try:
                        hook(exc)
                    except Exception as hook_exc:
                        console.print(f"[yellow]⚠ error hook: {hook_exc}[/yellow]")
                raise
            finally:
                if not exception_occurred:
                    # Standard after hooks
                    for hook in self._after_hooks:
                        try:
                            hook()
                        except Exception as exc:
                            console.print(f"[yellow]⚠ after hook: {exc}[/yellow]")

                    # Context-aware after hooks
                    for hook in self._after_ctx_hooks:
                        try:
                            hook(context, result)
                        except Exception as exc:
                            console.print(f"[yellow]⚠ after context hook: {exc}[/yellow]")

                # Finally hooks
                for hook in self._finally_hooks:
                    try:
                        hook()
                    except Exception as exc:
                        console.print(f"[yellow]⚠ finally hook: {exc}[/yellow]")

        return wrapper  # type: ignore[return-value]


class NamedHookManager:
    def __init__(self) -> None:
        """Create a registry of per-command :class:`HookManager` instances."""
        self._hooks: Dict[str, HookManager] = {}

    def for_command(self, command_name: str) -> HookManager:
        """Return (creating if necessary) the HookManager for *command_name*."""
        if command_name not in self._hooks:
            self._hooks[command_name] = HookManager()
        return self._hooks[command_name]

    def wrap(self, func: F) -> F:
        """Wrap *func* with its command-specific hooks, if any are registered."""
        command_name = func.__name__
        if command_name in self._hooks:
            return self._hooks[command_name].wrap(func)
        return func

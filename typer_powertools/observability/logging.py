"""
Helpers for integrating Python's ``logging`` module with Rich and middleware.

This module does **not** change existing middleware behavior; it provides
opt-in utilities for applications that want a richer logging story.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from rich.logging import RichHandler

from typer_powertools.observability.middleware import MiddlewareFunc


def configure_rich_logging(
    level: int | str = logging.INFO,
    *,
    log_time: bool = False,
    log_path: bool = False,
) -> None:
    """Configure the root logger with a Rich handler.

    Parameters
    ----------
    level:
        Logging level (e.g. ``logging.INFO`` or ``"INFO"``).
    log_time:
        If *True*, include timestamps in log output.
    log_path:
        If *True*, include file path and line number in log output.
    """
    if isinstance(level, str):
        level = logging.getLevelName(level.upper())

    show_path = log_path
    show_time = log_time

    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, show_path=show_path, show_time=show_time)],
        force=True,
    )


def logging_to_logger_middleware(
    logger: Optional[logging.Logger] = None,
    *,
    level: int = logging.INFO,
    log_args: bool = True,
    log_result: bool = False,
) -> MiddlewareFunc:
    """Middleware that logs invocations via the standard logging module.

    Parameters
    ----------
    logger:
        Optional logger instance. Defaults to ``logging.getLogger(__name__)``.
    level:
        Log level used for messages (default: ``logging.INFO``).
    log_args:
        Log function arguments.
    log_result:
        Log function return value.
    """
    _logger = logger or logging.getLogger(__name__)

    def middleware(next_fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        name = getattr(next_fn, "__name__", "<callable>")

        if log_args:
            _logger.log(level, "→ %s(args=%r, kwargs=%r)", name, args, kwargs)
        else:
            _logger.log(level, "→ %s()", name)

        result = next_fn(*args, **kwargs)

        if log_result:
            _logger.log(level, "← %s() -> %r", name, result)

        return result

    return middleware

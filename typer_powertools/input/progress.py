"""
Declarative progress bars and spinners for long-running Typer commands.

Usage
-----
    from typer_powertools.input.progress import progress_command, track_progress
    import typer, time

    app = typer.Typer()

    # 1. Simple spinner decorator (no total known)
    @app.command()
    @progress_command(description="Processing…")
    def process(files: int = 10):
        import time
        for i in range(files):
            time.sleep(0.2)
            yield              # each yield advances the spinner

    # 2. Track an iterable with a progress bar
    @app.command()
    def build(count: int = 20):
        for item in track_progress(range(count), description="Building…"):
            time.sleep(0.1)   # do work per item
"""

from __future__ import annotations

from contextlib import contextmanager
from functools import wraps
from typing import (
    Any,
    Callable,
    Generator,
    Iterable,
    Optional,
    TypeVar,
)

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    track,
)

console = Console()
F = TypeVar("F", bound=Callable[..., Any])
T = TypeVar("T")


def track_progress(
    iterable: Iterable[T],
    *,
    description: str = "Working…",
    total: Optional[int] = None,
    transient: bool = False,
) -> Iterable[T]:
    """Wrap an iterable with a Rich progress bar.

    Parameters
    ----------
    iterable:
        Any iterable to iterate over.
    description:
        Label shown to the left of the progress bar.
    total:
        Override the total count. Inferred automatically for sequences.
    transient:
        If *True*, clear the progress bar after completion.

    Example
    -------
    ::

        for row in track_progress(rows, description="Inserting rows…"):
            db.insert(row)
    """
    return track(
        iterable,
        description=description,
        total=total,
        transient=transient,
    )


@contextmanager
def progress_bar(
    total: int,
    *,
    description: str = "Working…",
    transient: bool = False,
) -> Generator[Callable[[int], None], None, None]:
    """Context manager yielding an ``advance(n)`` callable.

    Example
    -------
    ::

        with progress_bar(total=100, description="Uploading…") as advance:
            for chunk in chunks:
                upload(chunk)
                advance(1)
    """
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        transient=transient,
    )
    with progress:
        task = progress.add_task(description, total=total)

        def advance(n: int = 1) -> None:
            progress.advance(task, n)

        yield advance


@contextmanager
def spinner(
    description: str = "Working…",
    *,
    style: str = "green",
    spinner_name: str = "dots",
) -> Generator[None, None, None]:
    """Context manager that shows a Rich status spinner for the duration of the block.

    Parameters
    ----------
    description:
        Text shown next to the spinner.
    style:
        Rich color/style applied to the text.
    spinner_name:
        Rich spinner animation name (default: ``dots``).
    """
    with console.status(f"[{style}]{description}[/{style}]", spinner=spinner_name):
        yield


def progress_command(
    description: str = "Working…",
    *,
    total_param: Optional[str] = None,
    transient: bool = True,
    spinner_name: str = "dots",
    use_bar: bool = False,
) -> Callable[[F], F]:
    """Decorator to wrap a generator-based Typer command with a progress display.

    The decorated function should ``yield`` once per unit of work. If the
    function accepts a parameter matching *total_param*, its value is used as
    the progress bar total; otherwise a spinner is shown.

    Parameters
    ----------
    description:
        Label shown next to the spinner / bar.
    total_param:
        Name of the function parameter that holds the total work count.
        When provided, a determinate progress bar is used.
    transient:
        If *True*, the progress display disappears after completion.
    spinner_name:
        Rich spinner style (default: ``dots``).
    use_bar:
        Force a progress bar even if *total_param* is not supplied
        (will show as indeterminate bar).

    Example
    -------
    ::
        @app.command()
        @progress_command(description="Processing files…", total_param="count")
        def process(count: int = 10):
            for i in range(count):
                do_work(i)
                yield           # advances progress by 1
    """

    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            import inspect

            total: Optional[int] = None
            if total_param and total_param in kwargs:
                val = kwargs[total_param]
                if isinstance(val, int):
                    total = val

            is_gen = inspect.isgeneratorfunction(func)

            if is_gen:
                if total is not None or use_bar:
                    _run_with_bar(func, args, kwargs, description, total, transient)
                else:
                    _run_with_spinner(func, args, kwargs, description, spinner_name)
            else:
                # Non-generator: just show a spinner for the duration
                with console.status(f"[green]{description}[/green]", spinner=spinner_name):
                    return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def _run_with_spinner(
    func: Callable[..., Any],
    args: Any,
    kwargs: Any,
    description: str,
    spinner_name: str,
) -> None:
    """Drive a generator command while displaying an indeterminate spinner.

    Consumes every ``yield`` from *func* and pulses the spinner on each tick.
    """
    progress = Progress(
        SpinnerColumn(spinner_name),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
    )
    with progress:
        task = progress.add_task(description, total=None)
        for _ in func(*args, **kwargs):
            progress.advance(task, 0)  # pulse the spinner


def _run_with_bar(
    func: Callable[..., Any],
    args: Any,
    kwargs: Any,
    description: str,
    total: Optional[int],
    transient: bool,
) -> None:
    """Drive a generator command while displaying a determinate progress bar.

    Advances the bar by 1 on each ``yield`` from *func*.
    """
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        transient=transient,
    )
    with progress:
        task = progress.add_task(description, total=total)
        for _ in func(*args, **kwargs):
            progress.advance(task, 1)

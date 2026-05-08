"""
Transparent command logging and history for Typer apps.

Every invocation is recorded in a local SQLite database:
  • command name
  • arguments (JSON)
  • user (os.getlogin)
  • timestamp
  • exit code
  • duration (ms)

Usage
-----
    from typer_powertools.observability.audit import AuditMixin, audit_command
    import typer

    app = typer.Typer()

    @app.command()
    @audit_command(app_name="myapp")
    def deploy(env: str = "staging"):
        typer.echo(f"Deploying to {env}")

    # Built-in history viewer:
    # myapp audit history
    # myapp audit clear
"""

from __future__ import annotations

import getpass
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable, List, Optional, TypeVar

import typer
from rich.console import Console
from rich.table import Table

console = Console()
F = TypeVar("F", bound=Callable[..., Any])


def _default_db_path(app_name: str) -> Path:
    """Return a sensible platform-specific path for the audit DB."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    db_dir = base / app_name
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "audit.db"


def _get_connection(db_path: Path) -> sqlite3.Connection:
    """Open a SQLite connection with WAL mode and row factory enabled."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create the ``audit_log`` table if it does not already exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT    NOT NULL,
            user        TEXT    NOT NULL,
            command     TEXT    NOT NULL,
            args        TEXT    NOT NULL,
            exit_code   INTEGER NOT NULL DEFAULT 0,
            duration_ms REAL    NOT NULL DEFAULT 0
        )
        """)
    conn.commit()


def _record(
    db_path: Path,
    command: str,
    args: dict,
    exit_code: int,
    duration_ms: float,
) -> None:
    """Persist a single audit record to the SQLite database.

    Silently swallows all errors so audit failures never crash the app.
    """
    try:
        conn = _get_connection(db_path)
        _ensure_schema(conn)
        try:
            user = getpass.getuser()
        except Exception:
            user = "unknown"
        conn.execute(
            """
            INSERT INTO audit_log (timestamp, user, command, args, exit_code, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                user,
                command,
                json.dumps(args, default=str),
                exit_code,
                round(duration_ms, 2),
            ),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        # Audit should never crash the main program
        console.print(f"[dim yellow]⚠ audit: {exc}[/dim yellow]")


def audit_command(
    app_name: str = "app",
    db_path: Optional[Path] = None,
    log_args: bool = True,
    sensitive_params: Optional[List[str]] = None,
) -> Callable[[F], F]:
    """Decorator that transparently records every invocation of a command.

    Parameters
    ----------
    app_name:
        Application name — used to determine the default DB location.
    db_path:
        Explicit path for the SQLite audit database.
    log_args:
        Whether to store CLI arguments. Set *False* for privacy.
    sensitive_params:
        Param names whose values will be redacted (e.g. ``["password"]``).

    Example
    -------
    ::

        @app.command()
        @audit_command(app_name="myapp")
        def deploy(env: str = "staging", token: str = ""):
            ...
    """
    _db = db_path or _default_db_path(app_name)
    _sensitive = set(sensitive_params or [])

    def decorator(func: F) -> F:
        cmd_name = func.__name__.replace("_", "-")

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            exit_code = 0
            try:
                result = func(*args, **kwargs)
                return result
            except SystemExit as exc:
                exit_code = int(exc.code) if exc.code is not None else 0
                raise
            except Exception as exc:
                exit_code = 1
                raise
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                recorded_args: dict = {}
                if log_args:
                    for k, v in kwargs.items():
                        recorded_args[k] = "***" if k in _sensitive else v
                _record(
                    db_path=_db,
                    command=cmd_name,
                    args=recorded_args,
                    exit_code=exit_code,
                    duration_ms=duration_ms,
                )

        return wrapper  # type: ignore[return-value]

    return decorator


def audit_command_async(
    app_name: str = "app",
    db_path: Optional[Path] = None,
    log_args: bool = True,
    sensitive_params: Optional[List[str]] = None,
) -> Callable[[F], F]:
    """Async version of :func:`audit_command` for ``async def`` Typer commands.

    Transparently records every invocation of an async command to the same
    SQLite audit database.  The recording itself is synchronous (it runs in the
    ``finally`` block after ``await``-ing the command) so no additional async
    dependencies are required.

    Parameters
    ----------
    app_name:
        Application name — used to determine the default DB location.
    db_path:
        Explicit path for the SQLite audit database.  When *None*, the
        platform-specific default path is used
        (e.g. ``~/.local/share/<app_name>/audit.db`` on Linux).
    log_args:
        Whether to store CLI arguments in the audit record.
        Set *False* to avoid logging sensitive or large parameter values.
    sensitive_params:
        Parameter names whose values will be redacted in the audit log
        (stored as ``"***"``).  Useful for passwords, tokens, and API keys.

    Example
    -------
    ::

        @app.command()
        @audit_command_async(app_name="myapp", sensitive_params=["token"])
        async def deploy(env: str = "staging", token: str = ""):
            result = await async_deploy(env, token)
            typer.echo(f"✓ Deployed to {env}")
    """
    _db = db_path or _default_db_path(app_name)
    _sensitive = set(sensitive_params or [])

    def decorator(func: F) -> F:
        cmd_name = func.__name__.replace("_", "-")

        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            exit_code = 0
            try:
                result = await func(*args, **kwargs)
                return result
            except SystemExit as exc:
                exit_code = int(exc.code) if exc.code is not None else 0
                raise
            except Exception as exc:
                exit_code = 1
                raise
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                recorded_args: dict = {}
                if log_args:
                    for k, v in kwargs.items():
                        recorded_args[k] = "***" if k in _sensitive else v
                _record(
                    db_path=_db,
                    command=cmd_name,
                    args=recorded_args,
                    exit_code=exit_code,
                    duration_ms=duration_ms,
                )

        return wrapper  # type: ignore[return-value]

    return decorator


def register_audit_commands(
    app: typer.Typer,
    app_name: str = "app",
    db_path: Optional[Path] = None,
    command_group_name: str = "audit",
) -> None:
    """Register ``history`` and ``clear`` sub-commands under *app*.

    Adds:
      ``<cli> audit history [--limit N] [--command CMD]``
      ``<cli> audit clear [--yes]``
      ``<cli> audit stats``

    Parameters
    ----------
    app:
        Parent Typer app.
    app_name:
        Name used to resolve the default DB path.
    db_path:
        Override the default DB path.
    command_group_name:
        Name of the sub-command group (default: ``audit``).
    """
    _db = db_path or _default_db_path(app_name)
    audit_app = typer.Typer(name=command_group_name, help="Audit log management.")
    app.add_typer(audit_app)

    @audit_app.command("history")
    def history(
        limit: int = typer.Option(20, "--limit", "-n", help="Number of entries to show."),
        command: Optional[str] = typer.Option(
            None, "--command", "-c", help="Filter by command name."
        ),
        user: Optional[str] = typer.Option(None, "--user", "-u", help="Filter by username."),
    ) -> None:
        """Show recent command history."""
        conn = _get_connection(_db)
        _ensure_schema(conn)

        query = "SELECT * FROM audit_log WHERE 1=1"
        params: list = []
        if command:
            query += " AND command = ?"
            params.append(command)
        if user:
            query += " AND user = ?"
            params.append(user)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()
        conn.close()

        if not rows:
            console.print("[dim]No audit records found.[/dim]")
            return

        table = Table(title=f"Audit History — {app_name}", show_lines=True)
        table.add_column("#", style="dim", width=5)
        table.add_column("Timestamp", style="cyan")
        table.add_column("User", style="magenta")
        table.add_column("Command", style="bold green")
        table.add_column("Args", style="yellow")
        table.add_column("Exit", style="red")
        table.add_column("ms", style="dim")

        for row in reversed(rows):
            args_str = json.dumps(json.loads(row["args"]), separators=(",", ":"))
            exit_style = "green" if row["exit_code"] == 0 else "red"
            table.add_row(
                str(row["id"]),
                row["timestamp"],
                row["user"],
                row["command"],
                args_str,
                f"[{exit_style}]{row['exit_code']}[/{exit_style}]",
                str(row["duration_ms"]),
            )

        console.print(table)

    @audit_app.command("stats")
    def stats() -> None:
        """Show aggregate statistics from the audit log."""
        conn = _get_connection(_db)
        _ensure_schema(conn)

        total = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        by_cmd = conn.execute(
            "SELECT command, COUNT(*) as n FROM audit_log GROUP BY command ORDER BY n DESC"
        ).fetchall()
        avg_dur = conn.execute("SELECT AVG(duration_ms) FROM audit_log").fetchone()[0] or 0.0
        failures = conn.execute("SELECT COUNT(*) FROM audit_log WHERE exit_code != 0").fetchone()[0]
        conn.close()

        console.print(f"\n[bold]Total invocations:[/bold] {total}")
        console.print(f"[bold]Average duration:[/bold]  {avg_dur:.1f} ms")
        console.print(f"[bold]Failed runs:[/bold]       {failures}")

        if by_cmd:
            table = Table(title="Invocations by Command", show_lines=False)
            table.add_column("Command", style="green")
            table.add_column("Count", style="cyan", justify="right")
            for row in by_cmd:
                table.add_row(row["command"], str(row["n"]))
            console.print(table)

    @audit_app.command("clear")
    def clear(
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    ) -> None:
        """Clear all audit log entries."""
        if not yes:
            confirmed = typer.confirm("Delete all audit records?")
            if not confirmed:
                raise typer.Abort()
        conn = _get_connection(_db)
        _ensure_schema(conn)
        conn.execute("DELETE FROM audit_log")
        conn.commit()
        conn.close()
        console.print("[green]✓ Audit log cleared.[/green]")


class AuditMixin:
    """Mixin that attaches audit logging to a Typer app.

    Usage
    -----
    ::

        class MyApp(AuditMixin, app_name="myapp"):
            app = typer.Typer()
    """

    _audit_app_name: str = "app"
    _audit_db_path: Optional[Path] = None

    def __init_subclass__(
        cls,
        app_name: str = "app",
        db_path: Optional[Path] = None,
        **kwargs: Any,
    ) -> None:
        super().__init_subclass__(**kwargs)
        cls._audit_app_name = app_name
        cls._audit_db_path = db_path

    @classmethod
    def register_audit(cls, app: typer.Typer) -> None:
        """Attach audit sub-commands to *app*."""
        register_audit_commands(app, cls._audit_app_name, cls._audit_db_path)

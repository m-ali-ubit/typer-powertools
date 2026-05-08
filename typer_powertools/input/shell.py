"""
Interactive REPL / shell mode for Typer multi-command apps.

When you have a Typer app with several sub-commands, this extension lets
users drop into an interactive shell and run commands without re-invoking
the script each time — great for database CLIs, API clients, DevOps tools.

Usage
-----
    from typer_powertools.input.shell import ShellMixin, shell_command
    import typer

    app = typer.Typer()

    @app.command()
    def ping(host: str):
        typer.echo(f"pinging {host}")

    # Adds an interactive `shell` sub-command automatically:
    shell_command(app, prompt="myapp> ")

    if __name__ == "__main__":
        app()

    # Or use the mixin:
    class MyApp(ShellMixin, prompt="myapp> "):
        app = typer.Typer()
"""

from __future__ import annotations

import shlex
from typing import Any, Callable, Dict, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()


_QUIT_COMMANDS = {"exit", "quit", "q", ":q", "bye"}
_HELP_COMMANDS = {"help", "?", ":help"}


def _run_repl(
    app: typer.Typer,
    prompt: str,
    history_file: Optional[str],
    welcome_message: Optional[str],
    extra_commands: Dict[str, Callable[[], None]],
) -> None:
    """Run the interactive REPL loop.

    Sets up readline, prints the welcome banner, then repeatedly reads input
    from the user, dispatching to app commands or extra_commands until an exit
    keyword is entered or EOF is reached.
    """
    _setup_readline(history_file, app, extra_commands)
    if welcome_message:
        console.print(Panel(Text(welcome_message, style="bold green"), expand=False))

    console.print(
        f"[dim]Type [bold]help[/bold] to list commands or " f"[bold]exit[/bold] to quit.[/dim]"
    )

    while True:
        try:
            raw = _get_input(prompt)
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Bye![/dim]")
            break

        line = raw.strip()
        if not line:
            continue

        if line.lower() in _QUIT_COMMANDS:
            console.print("[dim]Bye![/dim]")
            break

        if line.lower() in _HELP_COMMANDS:
            _print_help(app, extra_commands)
            continue

        if line.lower() in extra_commands:
            try:
                extra_commands[line.lower()]()
            except Exception as exc:
                console.print(f"[red]Error:[/red] {exc}")
            continue

        try:
            args = shlex.split(line)
            app(args=args, standalone_mode=False)  # type: ignore[call-arg]
        except SystemExit:
            # Typer/Click calls sys.exit on --help or errors; catch it so the
            # REPL keeps running.
            pass
        except Exception as exc:
            console.print(f"[red]Error:[/red] {exc}")

    _save_readline(history_file)


def _get_input(prompt: str) -> str:
    """Read a single line from the user, propagating EOFError on Ctrl-D."""
    try:
        return input(prompt)
    except EOFError:
        raise


def _print_help(
    app: typer.Typer,
    extra_commands: Dict[str, Callable[[], None]],
) -> None:
    """Print a formatted list of all available REPL commands to the console."""
    console.print("\n[bold cyan]Available commands[/bold cyan]")
    for cmd in app.registered_commands:  # type: ignore[attr-defined]
        name = cmd.name or (cmd.callback.__name__ if cmd.callback else "?")
        doc = (cmd.callback.__doc__ or "").strip().splitlines()[0] if cmd.callback else ""
        console.print(f"  [green]{name:<20}[/green] {doc}")
    for group in getattr(app, "registered_groups", []):
        grp_app = group.typer_instance
        name = grp_app.info.name or "?"
        doc = grp_app.info.help or ""
        console.print(f"  [blue]{name:<20}[/blue] {doc} [dim](group)[/dim]")
    for name, func in extra_commands.items():
        doc = (func.__doc__ or "").strip().splitlines()[0]
        console.print(f"  [yellow]{name:<20}[/yellow] {doc}")
    console.print(f"  [dim]{'exit':<20}[/dim] Exit the shell")
    console.print()


def _setup_readline(
    history_file: Optional[str], app: typer.Typer, extra_commands: Dict[str, Callable[[], None]]
) -> None:
    """Configure readline tab-completion and load command history from disk.

    No-ops silently if readline is not available on the platform.
    """
    try:
        import readline

        commands = list(extra_commands.keys()) + list(_QUIT_COMMANDS) + list(_HELP_COMMANDS)
        for cmd in getattr(app, "registered_commands", []):
            name = cmd.name or getattr(cmd.callback, "__name__", None)
            if name:
                commands.append(name)

        def completer(text: str, state: int) -> Optional[str]:
            matches = [c for c in commands if c.startswith(text)]
            if state < len(matches):
                return matches[state]
            return None

        readline.set_completer(completer)
        readline.parse_and_bind("tab: complete")

        if history_file:
            try:
                readline.read_history_file(history_file)
            except FileNotFoundError:
                pass
        readline.set_history_length(1000)
    except ImportError:
        pass


def _save_readline(history_file: Optional[str]) -> None:
    """Persist readline history to disk. No-ops if readline is unavailable."""
    if not history_file:
        return
    try:
        import readline

        readline.write_history_file(history_file)
    except ImportError:
        pass


def shell_command(
    app: typer.Typer,
    *,
    prompt: str = ">>> ",
    history_file: Optional[str] = None,
    welcome_message: Optional[str] = None,
    extra_commands: Optional[Dict[str, Callable[[], None]]] = None,
    command_name: str = "shell",
    help: str = "Start an interactive REPL shell.",
) -> None:
    """Register a ``shell`` sub-command on *app* that opens a REPL.

    Parameters
    ----------
    app:
        The :class:`typer.Typer` instance to add the shell command to.
    prompt:
        The REPL prompt string (default: ``>>> ``).
    history_file:
        Path to persist readline command history across sessions.
    welcome_message:
        Optional banner shown when the shell starts.
    extra_commands:
        Dict of ``{name: callable}`` for additional one-word commands inside
        the shell (e.g. ``{"clear": lambda: os.system("clear")}``).
    command_name:
        Sub-command name to register (default: ``shell``).
    help:
        Help string for the shell sub-command.
    """
    _extra = extra_commands or {}

    @app.command(name=command_name, help=help)
    def _shell() -> None:
        _run_repl(
            app=app,
            prompt=prompt,
            history_file=history_file,
            welcome_message=welcome_message,
            extra_commands=_extra,
        )


class ShellMixin:
    """Mixin that registers a REPL shell command on a Typer app.

    Usage
    -----
    ::

        class MyApp(ShellMixin, prompt="myapp> "):
            app = typer.Typer()

        @MyApp.app.command()
        def ping(host: str): ...
    """

    _shell_prompt: str = ">>> "
    _shell_history: Optional[str] = None
    _shell_welcome: Optional[str] = None

    def __init_subclass__(
        cls,
        prompt: str = ">>> ",
        history_file: Optional[str] = None,
        welcome_message: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Capture shell configuration from class keyword arguments."""
        super().__init_subclass__(**kwargs)
        cls._shell_prompt = prompt
        cls._shell_history = history_file
        cls._shell_welcome = welcome_message

    @classmethod
    def register_shell(cls, app: typer.Typer) -> None:
        """Register the configured REPL shell command on *app*."""
        shell_command(
            app,
            prompt=cls._shell_prompt,
            history_file=cls._shell_history,
            welcome_message=cls._shell_welcome,
        )

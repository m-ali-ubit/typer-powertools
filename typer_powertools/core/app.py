"""
A unified builder for creating fully-featured Typer applications with
powertools extensions baked in (Audit, Config, Shell, etc.).

Usage
-----
    from typer_powertools.core.app import PowertyperApp

    app = (
        PowertyperApp("mycli")
        .with_shell()
        .with_audit()
        .with_i18n(locale_dir="locales", default_locale="en")
        .with_hooks()
        .build()
    )

    @app.command()
    def my_command():
        pass
"""

from pathlib import Path
from typing import Any, Optional

import typer

from typer_powertools.i18n.catalog import init as init_i18n
from typer_powertools.input.shell import shell_command
from typer_powertools.lifecycle.hooks import register_global_hooks
from typer_powertools.observability.audit import (
    audit_command,
    register_audit_commands,
)
from typer_powertools.observability.middleware import apply_global_middleware


class PowertyperApp:
    """Builder class for a fully-configured Typer application."""

    def __init__(self, name: str, **typer_kwargs: Any) -> None:
        """Create a new PowertyperApp builder.

        Parameters
        ----------
        name:
            Application name, used as the Typer app name and for audit/cache namespacing.
        **typer_kwargs:
            Extra keyword arguments forwarded directly to :class:`typer.Typer`.
        """
        self.name = name
        self.typer_kwargs = typer_kwargs
        self.app = typer.Typer(name=name, **typer_kwargs)

        self._enable_shell = False
        self._enable_audit = False
        self._enable_hooks = False
        self._enable_middleware = False
        self._audit_db_path: Optional[str] = None

    def with_shell(self) -> "PowertyperApp":
        """Adds a 'shell' sub-command to the CLI for interactive REPL."""
        self._enable_shell = True
        return self

    def with_audit(self, db_path: str = "~/.powertools_audit.db") -> "PowertyperApp":
        """Wraps all commands with auditing and adds history sub-commands."""
        self._enable_audit = True
        self._audit_db_path = db_path
        return self

    def with_i18n(
        self, locale_dir: str = "locales", default_locale: str = "en", auto_detect: bool = True
    ) -> "PowertyperApp":
        """Initializes the i18n translation system."""
        init_i18n(
            locale_dir=locale_dir,
            locale=None if auto_detect else default_locale,
            auto_detect=auto_detect,
        )
        return self

    def with_hooks(self) -> "PowertyperApp":
        """Applies globally registered hooks to all commands."""
        self._enable_hooks = True
        return self

    def with_middleware(self) -> "PowertyperApp":
        """Applies globally registered middleware to all commands."""
        self._enable_middleware = True
        return self

    def build(self) -> typer.Typer:
        """Finalizes the configuration and returns the fully built Typer app."""
        if self._enable_shell:
            # Attach the real interactive shell command.
            shell_command(self.app, prompt=f"{self.name}> ")

        if self._enable_audit:
            # Resolve an explicit DB path if provided, expanding user home.
            resolved_db_path: Optional[Path] = None
            if self._audit_db_path:
                resolved_db_path = Path(self._audit_db_path).expanduser()

            # Wrap all existing commands with audit logging.
            for cmd in getattr(self.app, "registered_commands", []):  # type: ignore[attr-defined]
                if cmd.callback:
                    original = cmd.callback
                    cmd.callback = audit_command(
                        app_name=self.name,
                        db_path=resolved_db_path,
                    )(original)

            # Add audit management sub-commands (history/stats/clear).
            register_audit_commands(self.app, app_name=self.name, db_path=resolved_db_path)

        if self._enable_hooks:
            register_global_hooks(self.app)

        if self._enable_middleware:
            apply_global_middleware(self.app)

        return self.app

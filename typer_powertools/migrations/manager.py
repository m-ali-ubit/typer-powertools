"""
Database-style migrations for configuration files.

Handle breaking changes in config schema over time by defining migration
functions that transform old configs to new formats.

Usage
-----
    from typer_powertools.migrations.manager import MigrationManager, migration
    import typer

    manager = MigrationManager(app_name="myapp")

    @manager.migration("v1_to_v2")
    def migrate_v1_to_v2(config: dict) -> dict:
        # Rename a field
        config["new_name"] = config.pop("old_name")
        return config

    @manager.migration("v2_to_v3")
    def migrate_v2_to_v3(config: dict) -> dict:
        # Add a new required field
        config["new_field"] = "default_value"
        return config

    # Automatically detect version and run migrations
    config = manager.load_and_migrate("config.json")
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import typer
from rich.console import Console
from rich.table import Table

console = Console()
MigrationFunc = Callable[[Dict[str, Any]], Dict[str, Any]]


class Migration:
    def __init__(
        self,
        name: str,
        from_version: str,
        to_version: str,
        func: MigrationFunc,
        description: str = "",
    ) -> None:
        """
        Parameters
        ----------
        name:
            Migration identifier (e.g., "rename_db_field").
        from_version:
            Source version string (e.g., "1.0", "v1").
        to_version:
            Target version string (e.g., "1.1", "v2").
        func:
            Migration function (old_config -> new_config).
        description:
            Human-readable description of the changes.
        """
        self.name = name
        self.from_version = from_version
        self.to_version = to_version
        self.func = func
        self.description = description

    def apply(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Apply this migration to a config dict."""
        console.print(f"[cyan]→ Applying migration: {self.name}[/cyan]")
        return self.func(config)


def _load_config_file(path: Path) -> Dict[str, Any]:
    """Load a config file in any supported format (JSON, TOML, YAML).

    Parameters
    ----------
    path:
        Path to the config file.

    Returns
    -------
    dict
        Parsed config dictionary.
    """
    suffix = path.suffix.lower()
    if suffix == ".toml":
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]
        with open(path, "rb") as f:
            return tomllib.load(f)
    elif suffix in (".yaml", ".yml"):
        import yaml

        with open(path) as f:
            return yaml.safe_load(f) or {}
    else:
        with open(path) as f:
            return json.load(f)


def _save_config_file(data: Dict[str, Any], path: Path) -> None:
    """Save a config dict to a file in any supported format.

    Parameters
    ----------
    data:
        Config dictionary to save.
    path:
        Destination file path.
    """
    suffix = path.suffix.lower()
    if suffix == ".toml":
        try:
            import tomli_w

            with open(path, "wb") as f:
                tomli_w.dump(data, f)
        except ImportError:
            try:
                import toml

                with open(path, "w") as f:
                    toml.dump(data, f)
            except ImportError:
                raise ImportError("Install 'tomli-w' or 'toml' to save TOML migrations.")
    elif suffix in (".yaml", ".yml"):
        import yaml

        with open(path, "w") as f:
            yaml.safe_dump(data, f)
    else:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)


class MigrationManager:
    def __init__(
        self,
        app_name: str = "app",
        version_key: str = "_version",
    ) -> None:
        """Create a migration manager.

        Parameters
        ----------
        app_name:
            Application name (informational, used for logging).
        version_key:
            Config dict key that stores the current schema version.
        """
        self.app_name = app_name
        self.version_key = version_key
        self.migrations: List[Migration] = []

    def migration(
        self,
        name: str,
        from_version: str = "",
        to_version: str = "",
        description: str = "",
    ) -> Callable[[MigrationFunc], MigrationFunc]:
        """Decorator to register a migration function.
        Parameters
        ----------
        name:
            Migration identifier.
        from_version:
            Source version (leave empty to auto-detect from order).
        to_version:
            Target version (leave empty to auto-detect from order).
        description:
            Human-readable description.

        Example
        -------
        ::
            @manager.migration("v1_to_v2", from_version="1.0", to_version="2.0")
            def migrate(config):
                config["renamed"] = config.pop("old_name")
                return config
        """

        def decorator(func: MigrationFunc) -> MigrationFunc:
            migration = Migration(
                name=name,
                from_version=from_version or str(len(self.migrations)),
                to_version=to_version or str(len(self.migrations) + 1),
                func=func,
                description=description,
            )
            self.migrations.append(migration)
            return func

        return decorator

    def get_current_version(self, config: Dict[str, Any]) -> str:
        """Return the version string stored in *config*, defaulting to ``"0"``."""
        return str(config.get(self.version_key, "0"))

    def set_version(self, config: Dict[str, Any], version: str) -> None:
        """Write *version* into *config* under :attr:`version_key`."""
        config[self.version_key] = version

    def get_migration_path(
        self, from_version: str, to_version: Optional[str] = None
    ) -> List[Migration]:
        """Find the sequence of migrations needed to upgrade.
        Parameters
        ----------
        from_version:
            Current config version.
        to_version:
            Target version (if *None*, upgrade to latest).

        Returns
        -------
        list[Migration]
            Ordered list of migrations to apply.
        """
        # If no target version, use the latest
        if to_version is None:
            if self.migrations:
                to_version = self.migrations[-1].to_version
            else:
                return []

        path: List[Migration] = []
        current = from_version

        while current != to_version:
            next_migration = None
            for mig in self.migrations:
                if mig.from_version == current:
                    next_migration = mig
                    break

            if not next_migration:
                raise ValueError(
                    f"No migration path from {from_version} to {to_version}. "
                    f"Stuck at version {current}."
                )

            path.append(next_migration)
            current = next_migration.to_version

        return path

    def migrate(
        self,
        config: Dict[str, Any],
        to_version: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Apply all necessary migrations to *config* in-memory.

        Parameters
        ----------
        config:
            The raw config dict to upgrade.
        to_version:
            Target version string. Defaults to the latest registered version.

        Returns
        -------
        dict
            The migrated config dict with the version key updated.
        """
        current_version = self.get_current_version(config)

        if to_version is None:
            if self.migrations:
                to_version = self.migrations[-1].to_version
            else:
                console.print("[dim]No migrations defined.[/dim]")
                return config

        if current_version == to_version:
            console.print(f"[dim]Already at version {to_version}[/dim]")
            return config

        console.print(f"[bold]Migrating from {current_version} → {to_version}[/bold]")

        # Get migration path
        try:
            path = self.get_migration_path(current_version, to_version)
        except ValueError as exc:
            console.print(f"[red]✗ {exc}[/red]")
            raise

        # Apply migrations
        migrated_config = config.copy()
        for migration in path:
            migrated_config = migration.apply(migrated_config)

        # Update version
        self.set_version(migrated_config, to_version)
        console.print(f"[green]✓ Migrated to version {to_version}[/green]")

        return migrated_config

    def load_and_migrate(
        self,
        config_path: Path | str,
        to_version: Optional[str] = None,
        backup: bool = True,
    ) -> Dict[str, Any]:
        """Load a config file, apply migrations, and optionally save.

        Parameters
        ----------
        config_path:
            Path to config file (JSON).
        to_version:
            Target version (if *None*, migrate to latest).
        backup:
            If *True*, create a backup before migrating.

        Returns
        -------
        dict
            Migrated config.
        """
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        # Helper functions to load and save multiple formats
        def _load_data(fp: Path) -> Dict[str, Any]:
            suffix = fp.suffix.lower()
            if suffix == ".toml":
                try:
                    import tomllib
                except ImportError:
                    import tomli as tomllib  # type: ignore
                with open(fp, "rb") as f_in:
                    return tomllib.load(f_in)
            elif suffix in (".yaml", ".yml"):
                import yaml

                with open(fp) as f_in:
                    return yaml.safe_load(f_in) or {}
            else:
                with open(fp) as f_in:
                    return json.load(f_in)

        def _save_data(data: Dict[str, Any], fp: Path) -> None:
            suffix = fp.suffix.lower()
            if suffix == ".toml":
                try:
                    import tomli_w

                    with open(fp, "wb") as f_out:
                        tomli_w.dump(data, f_out)
                except ImportError:
                    try:
                        import toml

                        with open(fp, "w") as f_out:
                            toml.dump(data, f_out)
                    except ImportError:
                        raise ImportError("Install 'tomli-w' or 'toml' to save TOML migrations.")
            elif suffix in (".yaml", ".yml"):
                import yaml

                with open(fp, "w") as f_out:
                    yaml.safe_dump(data, f_out)
            else:
                with open(fp, "w") as f_out:
                    json.dump(data, f_out, indent=2)

        # Load config
        config = _load_data(path)

        # Create backup
        if backup:
            backup_path = path.with_suffix(f".backup.{datetime.now():%Y%m%d_%H%M%S}{path.suffix}")
            _save_data(config, backup_path)
            console.print(f"[dim]Backup created: {backup_path}[/dim]")

        # Migrate
        migrated = self.migrate(config, to_version=to_version)

        # Save migrated config
        _save_data(migrated, path)

        console.print(f"[green]✓ Config updated: {path}[/green]")
        return migrated

    def list_migrations(self) -> None:
        """Print a table of all registered migrations."""
        if not self.migrations:
            console.print("[dim]No migrations registered.[/dim]")
            return

        table = Table(title="Registered Migrations", show_lines=True)
        table.add_column("Name", style="cyan bold")
        table.add_column("From", style="yellow")
        table.add_column("To", style="green")
        table.add_column("Description", style="dim")

        for mig in self.migrations:
            table.add_row(mig.name, mig.from_version, mig.to_version, mig.description)

        console.print(table)


# ---------------------------------------------------------------------------
# Migration commands
# ---------------------------------------------------------------------------


def register_migration_commands(
    app: typer.Typer,
    manager: MigrationManager,
    command_group_name: str = "migrate",
) -> None:
    """Register migration management sub-commands.

    Adds:
        <cli> migrate list
        <cli> migrate status <config_file>
        <cli> migrate apply <config_file> [--to-version X]

    Parameters
    ----------
    app:
        Parent Typer app.
    manager:
        MigrationManager instance.
    command_group_name:
        Name of the sub-command group.
    """
    migrate_app = typer.Typer(name=command_group_name, help="Config migration management.")
    app.add_typer(migrate_app)

    @migrate_app.command("list")
    def list_migrations() -> None:
        """List all registered migrations."""
        manager.list_migrations()

    @migrate_app.command("status")
    def status(config_file: Path) -> None:
        """Show current version of a config file."""
        if not config_file.exists():
            console.print(f"[red]✗ File not found: {config_file}[/red]")
            raise typer.Exit(code=1)

        config = _load_config_file(config_file)

        current = manager.get_current_version(config)
        latest = manager.migrations[-1].to_version if manager.migrations else "unknown"

        console.print(f"\n[bold]Config Version Status[/bold]")
        console.print(f"  File:            [cyan]{config_file}[/cyan]")
        console.print(f"  Current version: [yellow]{current}[/yellow]")
        console.print(f"  Latest version:  [green]{latest}[/green]")

        if current != latest:
            console.print(f"\n[yellow]⚠ Migrations available![/yellow]")
            try:
                path = manager.get_migration_path(current, latest)
                console.print(f"  {len(path)} migration(s) needed:")
                for mig in path:
                    console.print(f"    • {mig.name}")
            except ValueError as exc:
                console.print(f"  [red]{exc}[/red]")
        else:
            console.print(f"\n[green]✓ Up to date[/green]")

        console.print()

    @migrate_app.command("apply")
    def apply_migrations(
        config_file: Path,
        to_version: Optional[str] = typer.Option(
            None, "--to-version", help="Target version (default: latest)"
        ),
        no_backup: bool = typer.Option(False, "--no-backup", help="Skip backup creation"),
    ) -> None:
        """Apply migrations to a config file."""
        manager.load_and_migrate(config_file, to_version=to_version, backup=not no_backup)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def create_migration_template(name: str) -> str:
    """Generate a migration function template.

    Parameters
    ----------
    name:
        Migration name.

    Returns
    -------
    str
        Python code template.
    """
    return f'''
@manager.migration("{name}", from_version="X", to_version="Y")
def {name.replace("-", "_")}(config: dict) -> dict:
    """
    Migration: {name}
    
    Changes:
        - TODO: document changes
    """
    # TODO: Implement migration logic
    # Example: config["new_field"] = config.pop("old_field")
    return config
'''

"""
Dynamic plugin system for loading external commands at runtime.

Allows users to extend CLI tools with custom plugins, similar to kubectl plugins
or git extensions.

Usage
-----
    from typer_powertools.extensibility.plugins import PluginManager
    import typer

    app = typer.Typer()

    # Register some base commands
    @app.command()
    def status():
        typer.echo("Running")

    # Discover and load plugins
    plugins = PluginManager(app, plugin_prefix="myapp_")
    plugins.discover_from_path("~/.myapp/plugins/")
    plugins.discover_from_packages()  # finds installed packages with prefix
    plugins.load_all()

    if __name__ == "__main__":
        app()

Plugin Structure
----------------
A plugin can be:

1. A Python module with a `register(app: typer.Typer)` function:

    # myapp_example.py
    import typer

    def register(app: typer.Typer):
        @app.command(name="example")
        def example_cmd():
            typer.echo("Plugin command!")

2. A package with `__plugin__.py`:

    myapp_example/
        __init__.py
        __plugin__.py  # contains register(app) function

3. An entry point in setup.py/pyproject.toml:

    [project.entry-points."myapp.plugins"]
    example = "myapp_example:register"
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import typer
from rich.console import Console
from rich.table import Table

console = Console()


class PluginMetadata:
    def __init__(
        self,
        name: str,
        version: str = "unknown",
        description: str = "",
        author: str = "",
        source: str = "",
    ) -> None:
        """Store metadata about a discovered plugin.

        Parameters
        ----------
        name: Plugin name (without prefix).
        version: Package version string.
        description: Short description from the module docstring.
        author: Plugin author.
        source: File path, package name, or entry point string.
        """
        self.name = name
        self.version = version
        self.description = description
        self.author = author
        self.source = source


class PluginManager:
    def __init__(
        self,
        app: typer.Typer,
        plugin_prefix: str = "plugin_",
        entry_point_group: Optional[str] = None,
    ) -> None:
        """
        Parameters
        ----------
        app:
            The Typer app to register plugin commands on.
        plugin_prefix:
            Prefix for plugin module names (e.g., "myapp_" for "myapp_example").
        entry_point_group:
            Entry point group name for setuptools plugin discovery.
        """
        self.app = app
        self.plugin_prefix = plugin_prefix
        self.entry_point_group = entry_point_group
        self.discovered_plugins: Dict[str, Path | str] = {}
        self.loaded_plugins: Dict[str, PluginMetadata] = {}
        self.failed_plugins: Dict[str, str] = {}

    def discover_from_path(self, path: str | Path, recursive: bool = False) -> int:
        """Discover plugins from a filesystem path.

        Parameters
        ----------
        path:
            Directory to search for plugin files.
        recursive:
            If *True*, search subdirectories.

        Returns
        -------
        int
            Number of plugins discovered.
        """
        plugin_dir = Path(path).expanduser()
        if not plugin_dir.exists():
            console.print(f"[yellow]⚠ Plugin directory not found: {plugin_dir}[/yellow]")
            return 0

        count = 0
        pattern = "**/*.py" if recursive else "*.py"

        for py_file in plugin_dir.glob(pattern):
            if py_file.stem.startswith("_"):
                continue  # Skip __init__.py, __pycache__, etc.

            plugin_name = py_file.stem
            if self.plugin_prefix and not plugin_name.startswith(self.plugin_prefix):
                continue

            # Remove prefix for cleaner names
            clean_name = (
                plugin_name[len(self.plugin_prefix) :] if self.plugin_prefix else plugin_name
            )
            self.discovered_plugins[clean_name] = py_file
            count += 1

        return count

    def discover_from_packages(self) -> int:
        """Discover plugins from installed Python packages with the correct prefix.

        Uses :mod:`importlib.metadata` to enumerate *all installed* distributions
        and checks whether their top-level package name starts with
        :attr:`plugin_prefix`.  This finds plugins that are installed but have
        not yet been imported — unlike iterating ``sys.modules``.

        Returns
        -------
        int
            Number of plugins discovered.
        """
        count = 0
        if not self.plugin_prefix:
            return count

        try:
            from importlib.metadata import packages_distributions

            pkg_to_dist = packages_distributions()
            for pkg_name in pkg_to_dist:
                if pkg_name.startswith(self.plugin_prefix):
                    clean_name = pkg_name[len(self.plugin_prefix) :]
                    if clean_name not in self.discovered_plugins:
                        self.discovered_plugins[clean_name] = pkg_name
                        count += 1
        except Exception:
            # Fallback: scan sys.modules for already-imported packages
            for module_name in sys.modules:
                if module_name.startswith(self.plugin_prefix) and "." not in module_name:
                    clean_name = module_name[len(self.plugin_prefix) :]
                    if clean_name not in self.discovered_plugins:
                        self.discovered_plugins[clean_name] = module_name
                        count += 1

        return count

    def discover_from_entry_points(self) -> int:
        """Discover plugins registered via setuptools entry points.

        Uses the ``entry_point_group`` set on this manager.
        Requires the group name to be configured; returns 0 otherwise.

        Returns
        -------
        int
            Number of plugins discovered.
        """
        if not self.entry_point_group:
            return 0

        count = 0
        try:
            # Python 3.10+ uses importlib.metadata
            if sys.version_info >= (3, 10):
                from importlib.metadata import entry_points

                eps = entry_points(group=self.entry_point_group)
            else:
                # Python 3.9 uses different API
                from importlib.metadata import entry_points as eps_func

                eps = eps_func().get(self.entry_point_group, [])

            for ep in eps:
                self.discovered_plugins[ep.name] = f"entry_point:{ep.value}"
                count += 1
        except Exception as exc:
            console.print(f"[yellow]⚠ Entry point discovery failed: {exc}[/yellow]")

        return count

    def load(self, plugin_name: str) -> bool:
        """Load a single plugin by name.

        Parameters
        ----------
        plugin_name:
            Name of the plugin to load (without prefix).

        Returns
        -------
        bool
            *True* if loaded successfully, *False* otherwise.
        """
        if plugin_name in self.loaded_plugins:
            return True  # Already loaded

        if plugin_name not in self.discovered_plugins:
            console.print(f"[red]✗ Plugin not found: {plugin_name}[/red]")
            return False

        source = self.discovered_plugins[plugin_name]

        try:
            if isinstance(source, Path):
                module = self._load_from_file(source)
            elif isinstance(source, str) and source.startswith("entry_point:"):
                module = self._load_from_entry_point(source[len("entry_point:") :])
            else:
                module = importlib.import_module(str(source))

            if hasattr(module, "register"):
                register_func = getattr(module, "register")
                register_func(self.app)
            elif hasattr(module, "__plugin__"):
                plugin_module = importlib.import_module(f"{module.__name__}.__plugin__")
                if hasattr(plugin_module, "register"):
                    plugin_module.register(self.app)
                else:
                    raise AttributeError("__plugin__.py must define register(app)")
            else:
                raise AttributeError("Plugin must define register(app) function")

            metadata = self._extract_metadata(module, plugin_name, str(source))
            self.loaded_plugins[plugin_name] = metadata

            console.print(f"[green]✓[/green] Loaded plugin: [cyan]{plugin_name}[/cyan]")
            return True

        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            self.failed_plugins[plugin_name] = error_msg
            console.print(
                f"[red]✗[/red] Failed to load plugin [cyan]{plugin_name}[/cyan]: {error_msg}"
            )
            return False

    def load_all(self) -> int:
        """Attempt to load all discovered plugins.

        Returns
        -------
        int
            Number of successfully loaded plugins.
        """
        count = 0
        for plugin_name in list(self.discovered_plugins.keys()):
            if self.load(plugin_name):
                count += 1
        return count

    def unload(self, plugin_name: str) -> bool:
        """Unload a plugin (removes its commands from the app).

        Note: This is a best-effort operation and may not work for all plugins.

        Parameters
        ----------
        plugin_name:
            Name of the plugin to unload.

        Returns
        -------
        bool
            *True* if unloaded successfully.
        """
        if plugin_name not in self.loaded_plugins:
            return False

        # Remove from loaded plugins
        del self.loaded_plugins[plugin_name]
        console.print(f"[yellow]⊗[/yellow] Unloaded plugin: [cyan]{plugin_name}[/cyan]")
        return True

    def list_plugins(self, show_failed: bool = True) -> None:
        """Print a table of discovered and loaded plugins."""
        table = Table(title="Plugins", show_lines=True)
        table.add_column("Name", style="cyan")
        table.add_column("Status", style="bold")
        table.add_column("Version", style="dim")
        table.add_column("Description")

        for name in self.discovered_plugins:
            if name in self.loaded_plugins:
                meta = self.loaded_plugins[name]
                table.add_row(name, "[green]✓ loaded[/green]", meta.version, meta.description)
            elif name in self.failed_plugins and show_failed:
                error = self.failed_plugins[name]
                table.add_row(name, "[red]✗ failed[/red]", "", f"[dim]{error}[/dim]")
            else:
                table.add_row(name, "[dim]discovered[/dim]", "", "")

        console.print(table)

    def _load_from_file(self, path: Path) -> Any:
        """Load a module from a file path."""
        spec = importlib.util.spec_from_file_location(path.stem, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load module from {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def _load_from_entry_point(self, value: str) -> Any:
        """Load a module from an entry point string (e.g., 'package.module:function')."""
        parts = value.split(":")
        module_name = parts[0]
        module = importlib.import_module(module_name)

        if len(parts) > 1:
            attr_name = parts[1]
            func = getattr(module, attr_name)

            # Create a proxy class so load() can call .register(app) on it
            class EntryPointPlugin:
                register = staticmethod(func)
                __version__ = getattr(module, "__version__", "unknown")
                __doc__ = getattr(module, "__doc__", "")
                __author__ = getattr(module, "__author__", "")

            return EntryPointPlugin()

        return module

    def _extract_metadata(self, module: Any, name: str, source: str) -> PluginMetadata:
        """Extract metadata from a loaded plugin module."""
        # Fix string trimming for missing docstrings
        doc = getattr(module, "__doc__", "")
        if doc is None:
            doc = ""
        description = doc.strip().split("\n")[0]

        return PluginMetadata(
            name=name,
            version=getattr(module, "__version__", "unknown"),
            description=description,
            author=getattr(module, "__author__", ""),
            source=source,
        )


def register_plugin_commands(
    app: typer.Typer,
    plugin_manager: PluginManager,
    command_group_name: str = "plugins",
) -> None:
    """Register plugin management sub-commands.

    Adds:
        <cli> plugins list
        <cli> plugins load <name>
        <cli> plugins unload <name>
        <cli> plugins reload <name>

    Parameters
    ----------
    app:
        Parent Typer app.
    plugin_manager:
        PluginManager instance.
    command_group_name:
        Name of the sub-command group.
    """
    plugins_app = typer.Typer(name=command_group_name, help="Plugin management.")
    app.add_typer(plugins_app)

    @plugins_app.command("list")
    def list_plugins(
        failed: bool = typer.Option(True, "--failed/--no-failed", help="Show failed plugins."),
    ) -> None:
        plugin_manager.list_plugins(show_failed=failed)

    @plugins_app.command("load")
    def load_plugin(name: str) -> None:
        plugin_manager.load(name)

    @plugins_app.command("unload")
    def unload_plugin(name: str) -> None:
        if plugin_manager.unload(name):
            console.print(f"[green]✓ Unloaded: {name}[/green]")
        else:
            console.print(f"[red]✗ Plugin not loaded: {name}[/red]")

    @plugins_app.command("reload")
    def reload_plugin(name: str) -> None:
        plugin_manager.unload(name)
        plugin_manager.load(name)

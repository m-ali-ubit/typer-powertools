"""
Layered configuration file support for Typer apps.

Precedence (highest → lowest):
    1. CLI arguments passed explicitly
    2. Environment variables (prefixed)
    3. Config file (pyproject.toml / config.yaml / config.json / .env)
    4. Typer defaults

Usage
-----
    from typer_powertools.config.loader import ConfigMixin, config_option
    import typer

    app = typer.Typer()

    @app.command()
    @config_option()                       # adds --config / -c flag automatically
    def build(
        output: str = "dist",
        verbose: bool = False,
    ):
        typer.echo(f"Building → {output}")

    # Or subclass ConfigMixin for a richer API:
    class MyApp(ConfigMixin, app_name="myapp"):
        pass
"""

from __future__ import annotations

import inspect
import json
import os
import sys
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TypeVar, Union

import click
import typer
from rich.console import Console
from rich.table import Table

if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomllib  # type: ignore[no-redef]
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            tomllib = None  # type: ignore[assignment]

try:
    import yaml  # type: ignore[import]

    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

console = Console()
F = TypeVar("F", bound=Callable[..., Any])

_SUPPORTED_FORMATS = (".toml", ".yaml", ".yml", ".json")
_DEFAULT_SEARCH = [
    "pyproject.toml",
    ".config.toml",
    "config.toml",
    "config.yaml",
    "config.yml",
    "config.json",
]


def load_config(
    path: Optional[Union[str, Path]] = None,
    app_name: Optional[str] = None,
    search_parents: bool = True,
) -> Dict[str, Any]:
    """Load configuration from a file, returning a flat dict.

    Parameters
    ----------
    path:
        Explicit path to a config file. If *None*, search automatically.
    app_name:
        Tool name used to locate the ``[tool.<app_name>]`` section in
        ``pyproject.toml``.
    search_parents:
        Walk up parent directories when searching for config files.

    Returns
    -------
    dict
        Merged configuration values (flat keys matching CLI param names).
    """
    if path is not None:
        return _parse_file(Path(path), app_name)

    candidates = _find_config_files(search_parents)
    for candidate in candidates:
        try:
            data = _parse_file(candidate, app_name)
            if data:
                return data
        except Exception:
            continue

    return {}


def _find_config_files(search_parents: bool) -> List[Path]:
    """Return config file candidates, optionally walking up the directory tree."""
    cwd = Path.cwd()
    dirs: List[Path] = [cwd]
    if search_parents:
        dirs += list(cwd.parents)

    found: List[Path] = []
    for directory in dirs:
        for name in _DEFAULT_SEARCH:
            candidate = directory / name
            if candidate.exists():
                found.append(candidate)
    return found


def _parse_file(path: Path, app_name: Optional[str]) -> Dict[str, Any]:
    """Parse a single config file and return relevant section."""
    suffix = path.suffix.lower()

    if suffix == ".toml":
        try:
            return _parse_toml(path, app_name)
        except FileNotFoundError:
            return {}
    elif suffix in (".yaml", ".yml"):
        try:
            return _parse_yaml(path, app_name)
        except FileNotFoundError:
            return {}
    elif suffix == ".json":
        try:
            return _parse_json(path, app_name)
        except FileNotFoundError:
            return {}
    else:
        raise ValueError(f"Unsupported config format: {suffix}")


def _parse_toml(path: Path, app_name: Optional[str]) -> Dict[str, Any]:
    """Parse a TOML file and return the relevant section.

    For ``pyproject.toml``, returns ``[tool.<app_name>]``.
    For other TOML files, returns the top-level ``[<app_name>]`` section or the whole file.
    """
    if tomllib is None:
        raise ImportError("Install 'tomli' for Python < 3.11 to read TOML config files.")
    with open(path, "rb") as f:
        data = tomllib.load(f)

    if path.name == "pyproject.toml":
        # Look under [tool.<app_name>] → [tool.myapp]
        if app_name:
            return data.get("tool", {}).get(app_name, {})
        return {}
    else:
        # For ad-hoc config files, check if there is an app-specific or tool-specific table
        if app_name:
            if "tool" in data and app_name in data["tool"]:
                return data["tool"][app_name]
            if app_name in data:
                return data[app_name]
        return data


def _parse_yaml(path: Path, app_name: Optional[str]) -> Dict[str, Any]:
    """Parse a YAML file and return the relevant section.

    Returns the ``<app_name>`` sub-dict if present, otherwise the whole dict.
    """
    if not _YAML_AVAILABLE:
        raise ImportError("Install 'pyyaml' to read YAML config files.")
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return data.get(app_name, data) if app_name and app_name in data else data


def _parse_json(path: Path, app_name: Optional[str]) -> Dict[str, Any]:
    """Parse a JSON file and return the relevant section.

    Returns the ``<app_name>`` sub-dict if present, otherwise the whole dict.
    """
    with open(path) as f:
        data = json.load(f)
    return data.get(app_name, data) if app_name and app_name in data else data


def _load_env_vars(
    prefix: str, keys: List[str], env_file: Optional[str] = ".env"
) -> Dict[str, Any]:
    """Return values from environment variables matching ``<PREFIX>_<KEY>``."""
    result: Dict[str, Any] = {}
    prefix_upper = prefix.upper().rstrip("_") + "_"

    # Try to load .env file via python-dotenv if available
    try:
        from dotenv import dotenv_values

        if env_file and os.path.exists(env_file):
            dotenv_cfg = dotenv_values(env_file)
            for k, v in dotenv_cfg.items():
                if k.startswith(prefix_upper) and v is not None:
                    key = k[len(prefix_upper) :].lower().replace("_", "-")
                    if key in keys:
                        result[key] = _coerce(v)
    except ImportError:
        pass
    # Standard environment variables (override .env)
    for key in keys:
        env_key = prefix_upper + key.upper().replace("-", "_")
        value = os.environ.get(env_key)
        if value is not None:
            result[key] = _coerce(value)
    return result


def _coerce(value: str) -> Any:
    """Coerce a raw string value to the most appropriate Python type.

    Converts ``"true"`` / ``"false"`` to bool, numeric strings to int/float,
    and leaves everything else as a string.
    """
    if isinstance(value, str):
        if value in ("true", "True", "TRUE", "yes", "Yes", "1"):
            return True
        if value in ("false", "False", "FALSE", "no", "No", "0"):
            return False
        if value.strip() != value:
            return value
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def config_option(
    app_name: Optional[str] = None,
    env_prefix: Optional[str] = None,
    search_parents: bool = True,
) -> Callable[[F], F]:
    """Decorator that injects a ``--config`` flag and merges layered config.

    Parameters
    ----------
    app_name:
        Name used to find the ``[tool.<app_name>]`` section in pyproject.toml.
    env_prefix:
        Environment variable prefix (default: *app_name* or ``APP``).
    search_parents:
        Walk parent directories when searching for config files.

    Example
    -------
    ::
        @app.command()
        @config_option(app_name="myapp", env_prefix="MYAPP")
        def build(output: str = "dist", verbose: bool = False):
            ...
    """

    def decorator(func: F) -> F:
        """Wrap *func* to inject layered config before the command runs."""
        sig = inspect.signature(func)

        if "config" in sig.parameters:
            return func

        new_params = list(sig.parameters.values())
        new_params.append(
            inspect.Parameter(
                "config",
                inspect.Parameter.KEYWORD_ONLY,
                default=typer.Option(
                    None,
                    "--config",
                    "-c",
                    help="Path to a config file (.toml/.yaml/.json). Auto-detected if omitted.",
                    show_default=False,
                ),
                annotation=Optional[Path],
            )
        )

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            """Resolve config from file, env vars, and CLI, then call *func*."""
            config = kwargs.pop("config", None)
            prefix = env_prefix or app_name or "APP"
            file_cfg = load_config(
                path=config,
                app_name=app_name,
                search_parents=search_parents,
            )
            param_names = list(sig.parameters.keys())
            env_cfg = _load_env_vars(prefix, param_names, env_file=".env")
            defaults: Dict[str, Any] = {
                k: v.default
                for k, v in sig.parameters.items()
                if v.default is not inspect.Parameter.empty
            }

            merged: Dict[str, Any] = {}
            for key in param_names:
                default = defaults.get(key)
                file_val = file_cfg.get(key)
                env_val = env_cfg.get(key)
                cli_val = kwargs.get(key, default)

                cli_explicit = False
                ctx = click.get_current_context(silent=True)
                if ctx and key in ctx.params:
                    source = ctx.get_parameter_source(key)
                    if source and source.name == "COMMANDLINE":
                        cli_explicit = True
                else:
                    cli_explicit = cli_val != default

                if cli_explicit:
                    merged[key] = cli_val
                elif env_val is not None:
                    merged[key] = env_val
                elif file_val is not None:
                    merged[key] = file_val
                else:
                    merged[key] = cli_val
            return func(*args, **merged)

        wrapper.__signature__ = sig.replace(parameters=new_params)  # type: ignore
        return wrapper  # type: ignore[return-value]

    return decorator


class ConfigMixin:
    """Mixin that adds :meth:`show_config` and :meth:`load_config` helpers.
    Usage
    -----
    ::
        class MyApp(ConfigMixin, app_name="myapp"):
            app = typer.Typer()

        @MyApp.app.command()
        def run(): ...
    """

    _app_name: Optional[str] = None

    def __init_subclass__(cls, app_name: Optional[str] = None, **kwargs: Any) -> None:
        """Capture the ``app_name`` keyword argument on subclass creation."""
        super().__init_subclass__(**kwargs)
        cls._app_name = app_name

    @classmethod
    def get_config(
        cls,
        path: Optional[Union[str, Path]] = None,
    ) -> Dict[str, Any]:
        """Load and return the resolved configuration dict for this app.

        Parameters
        ----------
        path:
            Optional explicit config file path. Auto-detected if omitted.

        Returns
        -------
        dict
            Merged configuration values.
        """
        return load_config(path=path, app_name=cls._app_name)

    @classmethod
    def show_config(
        cls,
        path: Optional[Union[str, Path]] = None,
    ) -> None:
        """Print the resolved configuration as a Rich table.

        Parameters
        ----------
        path:
            Optional explicit config file path. Auto-detected if omitted.
        """
        cfg = cls.get_config(path=path)
        table = Table(title=f"Config — {cls._app_name or 'app'}", show_lines=True)
        table.add_column("Key", style="cyan bold")
        table.add_column("Value", style="green")
        for k, v in cfg.items():
            table.add_row(str(k), str(v))
        console.print(table)

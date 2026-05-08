"""
Pydantic integration for strongly validated configuration models.

Usage
-----
    from pydantic import BaseModel
    from typer_powertools.config.schema import pydantic_config_option

    class AppConfig(BaseModel):
        host: str = "0.0.0.0"
        port: int = 8080
        debug: bool = False

    @app.command()
    @pydantic_config_option(AppConfig, app_name="myapp")
    def serve(cfg: AppConfig):
        typer.echo(f"Serving {cfg.host}:{cfg.port}")
"""

import functools
import inspect
from typing import Any, Callable, Dict, Optional, Type, TypeVar

import typer
from click import get_current_context

from typer_powertools.config.loader import _load_env_vars, load_config
from typer_powertools.migrations.manager import MigrationManager

try:
    from pydantic import BaseModel, ValidationError

    _PYDANTIC_AVAILABLE = True
except ImportError:
    _PYDANTIC_AVAILABLE = False
    BaseModel = Any  # type: ignore

F = TypeVar("F", bound=Callable[..., Any])


def pydantic_config_option(
    model: Type[BaseModel],
    app_name: Optional[str] = None,
    env_prefix: Optional[str] = None,
    search_parents: bool = True,
    inject_name: str = "cfg",
) -> Callable[[F], F]:
    """Decorator that loads configuration, validates it via Pydantic, and injects the model instance.

    Parameters
    ----------
    model:
        Subclass of `pydantic.BaseModel` defining the config schema.
    app_name:
        Tool name for finding config sections (e.g. `[tool.<app_name>]`).
    env_prefix:
        Prefix for environment variables. Defaults to `app_name` or "APP".
    search_parents:
        If True, walk up parent directories to find config files.
    inject_name:
        The kwargs parameter name to inject the initialized model into.
    """
    if not _PYDANTIC_AVAILABLE:
        raise ImportError("The 'pydantic' package is required to use 'pydantic_config_option'.")

    def decorator(func: F) -> F:
        # Build a new signature that removes the inject_name param so Typer
        # never tries to resolve the Pydantic model as a Click type.
        sig = inspect.signature(func)
        params_without_cfg = [p for name, p in sig.parameters.items() if name != inject_name]
        # Add the --config option as an extra parameter
        config_param = inspect.Parameter(
            "config",
            inspect.Parameter.KEYWORD_ONLY,
            default=typer.Option(
                None,
                "--config",
                "-c",
                help="Path to a config file. Auto-detected if omitted.",
                show_default=False,
            ),
            annotation=Optional[str],
        )
        new_params = params_without_cfg + [config_param]
        new_sig = sig.replace(parameters=new_params)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            config: Optional[str] = kwargs.pop("config", None)
            prefix = env_prefix or app_name or "APP"
            file_cfg = load_config(
                path=config,
                app_name=app_name,
                search_parents=search_parents,
            )
            param_names = (
                list(model.model_fields.keys())
                if hasattr(model, "model_fields")
                else list(model.__fields__.keys())
            )
            env_cfg = _load_env_vars(prefix, param_names, env_file=".env")
            merged_dict: Dict[str, Any] = {}
            for key in param_names:
                file_val = file_cfg.get(key)
                env_val = env_cfg.get(key)

                # Check if CLI passed the argument EXPLICITLY via standard kwargs
                cli_val = kwargs.get(key)
                cli_explicit = False
                ctx = get_current_context(silent=True)
                if ctx and key in ctx.params:
                    source = ctx.get_parameter_source(key)
                    if source and source.name == "COMMANDLINE":
                        cli_explicit = True

                if cli_explicit and cli_val is not None:
                    merged_dict[key] = cli_val
                elif env_val is not None:
                    merged_dict[key] = env_val
                elif file_val is not None:
                    merged_dict[key] = file_val
                elif key in kwargs:
                    merged_dict[key] = kwargs[key]

            # Validate merged dict into a Pydantic Model instance
            try:
                cfg_instance = model(**merged_dict)
            except ValidationError as e:
                import rich.console

                rich.console.Console().print(f"[red]Configuration Validation Error:[/red]\n{e}")
                raise typer.Exit(code=1)

            # Clean up individual kwargs that were absorbed into the Pydantic model
            func_sig = inspect.signature(func)
            for key in list(kwargs.keys()):
                if key not in func_sig.parameters and key in param_names:
                    kwargs.pop(key)

            # Inject the validated model
            kwargs[inject_name] = cfg_instance

            return func(*args, **kwargs)

        wrapper.__signature__ = new_sig  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorator


def versioned_pydantic_config_option(
    model: Type[BaseModel],
    manager: MigrationManager,
    app_name: Optional[str] = None,
    env_prefix: Optional[str] = None,
    search_parents: bool = True,
    inject_name: str = "cfg",
    to_version: Optional[str] = None,
) -> Callable[[F], F]:
    """Decorator that combines migrations + config loading + Pydantic validation.

    This is a higher-level version of :func:`pydantic_config_option` that:

    1. Loads raw config from disk.
    2. Applies ``MigrationManager`` migrations (updating the file on disk when an
       explicit ``--config`` path is provided).
    3. Merges in environment variables and explicit CLI arguments.
    4. Validates into a Pydantic model instance and injects it into the command.

    Parameters
    ----------
    model:
        Subclass of `pydantic.BaseModel` defining the config schema.
    manager:
        A :class:`MigrationManager` instance that knows how to migrate configs.
    app_name:
        Tool name for finding config sections (e.g. `[tool.<app_name>]`).
    env_prefix:
        Prefix for environment variables. Defaults to `app_name` or "APP".
    search_parents:
        If True, walk up parent directories to find config files when no
        explicit ``--config`` path is provided.
    inject_name:
        The kwargs parameter name to inject the initialized model into.
    to_version:
        Optional explicit target version for migrations. If *None*, migrate
        to the latest version known by the manager.
    """
    if not _PYDANTIC_AVAILABLE:
        raise ImportError(
            "The 'pydantic' package is required to use 'versioned_pydantic_config_option'."
        )

    def decorator(func: F) -> F:
        # Build a new signature that removes the inject_name param so Typer
        # never tries to resolve the Pydantic model as a Click type.
        sig_orig = inspect.signature(func)
        params_without_cfg = [p for name, p in sig_orig.parameters.items() if name != inject_name]
        config_param = inspect.Parameter(
            "config",
            inspect.Parameter.KEYWORD_ONLY,
            default=typer.Option(
                None,
                "--config",
                "-c",
                help="Path to a config file. Auto-detected if omitted.",
                show_default=False,
            ),
            annotation=Optional[str],
        )
        new_params = params_without_cfg + [config_param]
        new_sig = sig_orig.replace(parameters=new_params)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            config: Optional[str] = kwargs.pop("config", None)
            prefix = env_prefix or app_name or "APP"

            # 1) Load base config and apply migrations
            if config:
                # When a concrete path is provided, update the file on disk as well.
                base_cfg = manager.load_and_migrate(config, to_version=to_version, backup=True)
            else:
                # Reuse the standard loader search strategy, then migrate in-memory only.
                base_cfg = load_config(
                    path=None,
                    app_name=app_name,
                    search_parents=search_parents,
                )
                base_cfg = manager.migrate(base_cfg, to_version=to_version)

            # 2) Load environment variables for known model fields
            if hasattr(model, "model_fields"):
                param_names = list(model.model_fields.keys())
            else:  # Pydantic v1 fallback
                param_names = list(model.__fields__.keys())  # type: ignore[attr-defined]
            env_cfg = _load_env_vars(prefix, param_names, env_file=".env")

            # 3) Merge precedence: CLI (explicit) > env > migrated file > Typer defaults
            merged_dict: Dict[str, Any] = {}
            ctx = get_current_context(silent=True)

            for key in param_names:
                file_val = base_cfg.get(key)
                env_val = env_cfg.get(key)

                cli_val = kwargs.get(key)
                cli_explicit = False
                if ctx and key in ctx.params:
                    source = ctx.get_parameter_source(key)
                    if source and getattr(source, "name", "") == "COMMANDLINE":
                        cli_explicit = True

                if cli_explicit and cli_val is not None:
                    merged_dict[key] = cli_val
                elif env_val is not None:
                    merged_dict[key] = env_val
                elif file_val is not None:
                    merged_dict[key] = file_val
                elif key in kwargs:
                    merged_dict[key] = kwargs[key]

            # 4) Validate merged dict into a Pydantic model instance
            try:
                cfg_instance = model(**merged_dict)
            except ValidationError as e:
                import rich.console

                rich.console.Console().print(
                    f"[red]Configuration Validation Error (after migrations):[/red]\n{e}"
                )
                raise typer.Exit(code=1)

            # Clean up kwargs that were absorbed into the model and are not part
            # of the original command signature to avoid double-passing.
            func_sig = inspect.signature(func)
            for key in list(kwargs.keys()):
                if key not in func_sig.parameters and key in param_names:
                    kwargs.pop(key)

            kwargs[inject_name] = cfg_instance
            return func(*args, **kwargs)

        wrapper.__signature__ = new_sig  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorator

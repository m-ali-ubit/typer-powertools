"""
Extended batteries for Typer — 12 CLI extensions.

Modules
-------
- config      : Layered config file support (pyproject.toml / .env / YAML / JSON)
- shell       : Interactive REPL / shell mode for multi-command apps
- progress    : Declarative progress bars and spinners for long-running commands
- audit       : Transparent command logging and history (SQLite-backed)
- i18n        : Internationalization / localization for help text
- hooks       : Pre/post command execution hooks for setup/teardown
- cache       : Command output caching with TTL
- middleware  : Request/response pipeline for commands
- plugins     : Dynamic plugin discovery and loading system
- wizard      : Interactive setup wizards for complex configurations
- templates   : File/project generation from Jinja2 templates
- migrations  : Version and migrate configuration files
"""

from typer_powertools.config.loader import ConfigMixin, config_option, load_config
from typer_powertools.config.schema import (
    pydantic_config_option,
    versioned_pydantic_config_option,
)
from typer_powertools.core.app import PowertyperApp
from typer_powertools.core.decorators import full_stack_command
from typer_powertools.extensibility.plugins import (
    PluginManager,
    register_plugin_commands,
)
from typer_powertools.extensibility.templates import (
    TemplateEngine,
    TemplateRepository,
    render_single_file,
    render_template,
)
from typer_powertools.i18n.catalog import (
    I18nMixin,
    MessageCatalog,
    set_locale,
    translate,
)
from typer_powertools.input.progress import (
    progress_bar,
    progress_command,
    spinner,
    track_progress,
)
from typer_powertools.input.shell import ShellMixin, shell_command
from typer_powertools.input.wizard import (
    Step,
    Wizard,
    WizardBuilder,
    quick_wizard,
)
from typer_powertools.lifecycle.cache import (
    CacheManager,
    cached_command,
    cached_command_async,
    register_cache_commands,
    temporary_cache,
)
from typer_powertools.lifecycle.hooks import (
    ContextHookManager,
    HookManager,
    NamedHookManager,
    on_after,
    on_before,
    on_error,
    on_finally,
    wrap_command,
)
from typer_powertools.migrations.manager import (
    MigrationManager,
    register_migration_commands,
)
from typer_powertools.observability.audit import (
    AuditMixin,
    audit_command,
    audit_command_async,
    register_audit_commands,
)
from typer_powertools.observability.logging import (
    configure_rich_logging,
    logging_to_logger_middleware,
)
from typer_powertools.observability.middleware import (
    Middleware,
    use_middleware,
)

__all__ = [
    "ConfigMixin",
    "config_option",
    "load_config",
    "pydantic_config_option",
    "versioned_pydantic_config_option",
    "ShellMixin",
    "shell_command",
    "progress_command",
    "progress_bar",
    "spinner",
    "track_progress",
    "AuditMixin",
    "audit_command",
    "audit_command_async",
    "register_audit_commands",
    "I18nMixin",
    "MessageCatalog",
    "set_locale",
    "translate",
    "ContextHookManager",
    "HookManager",
    "NamedHookManager",
    "on_after",
    "on_before",
    "on_error",
    "on_finally",
    "wrap_command",
    "CacheManager",
    "cached_command",
    "cached_command_async",
    "register_cache_commands",
    "temporary_cache",
    "Middleware",
    "use_middleware",
    "configure_rich_logging",
    "logging_to_logger_middleware",
    "PluginManager",
    "register_plugin_commands",
    "Step",
    "Wizard",
    "WizardBuilder",
    "quick_wizard",
    "TemplateEngine",
    "TemplateRepository",
    "render_single_file",
    "render_template",
    "MigrationManager",
    "register_migration_commands",
    "PowertyperApp",
    "full_stack_command",
]

__version__ = "0.2.0"

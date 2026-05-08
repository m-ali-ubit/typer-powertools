# typer-powertools Quick Reference

## Import Cheat Sheet

```python
# Config
from typer_powertools.config.loader import config_option, load_config, ConfigMixin
from typer_powertools.config.schema import (
    pydantic_config_option,
    versioned_pydantic_config_option,
)

# Shell
from typer_powertools.input.shell import shell_command, ShellMixin

# Progress
from typer_powertools.input.progress import (
    progress_command,
    track_progress,
    spinner,      # ← Context manager
    progress_bar, # ← Context manager
)

# Audit
from typer_powertools.observability.audit import (
    audit_command,
    audit_command_async,
    register_audit_commands,
    AuditMixin,
)

# i18n
from typer_powertools.i18n.catalog import (
    set_locale,
    translate,
    I18nMixin,
    MessageCatalog, # ← In-memory translations
)

# Hooks
from typer_powertools.lifecycle.hooks import (
    HookManager,
    ContextHookManager, # ← Context-aware hooks
    NamedHookManager,   # ← Command-specific hooks
    on_before,
    on_after,
    on_error,
    on_finally,         # ← New!
)

# Cache
from typer_powertools.lifecycle.cache import (
    CacheManager,
    cached_command,
    register_cache_commands,
    temporary_cache,    # ← Context manager
)

# Middleware
from typer_powertools.observability.middleware import (
    use_middleware,
    timing_middleware,
    retry_middleware,
    logging_middleware,
)

# Plugins
from typer_powertools.extensibility.plugins import (
    PluginManager,
    register_plugin_commands,
)

# Wizard
from typer_powertools.input.wizard import Wizard, WizardBuilder, quick_wizard, Step

# Templates
from typer_powertools.extensibility.templates import (
    TemplateEngine,
    render_template,
    TemplateRepository, # ← Template management
)

# Migrations
from typer_powertools.migrations.manager import (
    MigrationManager,
    register_migration_commands,
)

# Core app builder & composite decorator
from typer_powertools.core.app import PowertyperApp
from typer_powertools.core.decorators import full_stack_command

# Logging (observability)
from typer_powertools.observability.logging import (
    configure_rich_logging,
    logging_to_logger_middleware,
)

# Testing helpers
from typer_powertools.testing import run_cli, temp_config_file
```

---

## Decorator Stacking Order

When combining multiple decorators, use this order (top to bottom):

```python
@app.command()                          # 1. Typer command decorator (always first)
@audit_command(app_name="myapp")        # 2. Audit (outermost wrapper)
@cached_command(ttl=300)                # 3. Cache (before hooks/middleware)
@hooks.wrap                             # 4. Hooks (setup/teardown)
@use_middleware([auth, timing])         # 5. Middleware (request pipeline)
@config_option(app_name="myapp")        # 6. Config (modifies arguments)
@progress_command(description="Work…")  # 7. Progress (innermost, wraps execution)
def my_command(arg: str):
    pass
```

---

## Common Patterns

### 1. In-Memory Translations (i18n)

No JSON files needed. Manage translations directly in code:

```python
catalog = MessageCatalog()
catalog.add("en", "welcome", "Welcome, {name}!")
catalog.add("de", "welcome", "Willkommen, {name}!")

catalog.activate("de")
msg = translate("welcome", name="Ali") # "Willkommen, Ali!"
```

### 2. Context-Aware Hooks

Hooks that receive the Typer `Context`:

```python
hooks = ContextHookManager()

@hooks.before
def setup(ctx: typer.Context):
    typer.echo(f"Starting {ctx.command.name}")

@app.command()
@hooks.wrap
def deploy():
    pass
```

### 3. Progress & Spinner (Manual Control)

Instead of decorating the whole command, use context managers:

```python
@app.command()
def build():
    with spinner("Compiling..."):
        # ... long task ...
        pass
    
    with progress_bar() as progress:
        task = progress.add_task("Uploading", total=100)
        for i in range(100):
            # ... work ...
            progress.update(task, advance=1)
```

### 4. Temporary Cache

Override cache settings for a specific block of code:

```python
with temporary_cache(ttl=60): # 1 minute instead of default
    # ... code using cached functions ...
    pass
```

### 5. Template Repository

Manage and render named templates:

```python
repo = TemplateRepository("./templates")
repo.add("dockerfile", "FROM {{ image }}\nRUN {{ cmd }}")

# Render to string
content = repo.render("dockerfile", image="python:3.12", cmd="pip install .")

# Render to file
repo.render_to_file("dockerfile", "Dockerfile", image="python:3.12")
```

---

## Management Commands Quick Add

```python
# Add all management sub-apps at once
register_audit_commands(app, app_name="myapp")
register_cache_commands(app, app_name="myapp")
register_plugin_commands(app, plugin_manager)
register_migration_commands(app, migration_manager)

# Now your CLI has:
# myapp audit history / stats / clear
# myapp cache stats / clear / info
# myapp plugins list / load / unload
# myapp migrate list / status / apply
```

---

## Environment Variables

```bash
# Config module
MYAPP_OUTPUT=dist           # Overrides config file
MYAPP_VERBOSE=true          # Boolean coercion

# i18n module
LANG=de_DE.UTF-8           # Auto-detected locale
LANGUAGE=fr                # Alternative detection

# Cache & Audit (Platform-Aware defaults)
# Linux:   ~/.cache/myapp/  |  ~/.local/share/myapp/
# macOS:   ~/Library/Caches/myapp/  |  ~/Library/Application Support/myapp/
# Windows: %LOCALAPPDATA%\myapp\  |  %APPDATA%\myapp\
```

---

## Testing Tips

```python
from typer_powertools.testing import run_cli, temp_config_file

# Invoke CLI with isolated runner
result = run_cli(app, ["build", "--env", "prod"])
assert result.exit_code == 0

# Test with temporary JSON config (auto-cleanup)
with temp_config_file({"output": "test"}, suffix=".json") as path:
    result = run_cli(app, ["build", "--config", str(path)])

# Test with env vars
result = run_cli(app, ["build"], env={"MYAPP_VERBOSE": "true"})
```

---

## Common Gotchas

### ❌ Wrong: Config decorator above @app.command()
```python
@config_option(app_name="myapp")
@app.command()
def cmd(): pass
```

### ✅ Correct: Config after @app.command()
```python
@app.command()
@config_option(app_name="myapp")
def cmd(): pass
```

### ❌ Wrong: Positional args in `run_cli`
```python
# Click/Typer often fail if options are passed as positional args in tests
run_cli(app, ["deploy", "production"]) 
```

### ✅ Correct: Use explicit flags
```python
run_cli(app, ["deploy", "--env", "production"])
```

"""
Comprehensive showcase of all 12 modules and every public API.

  Module coverage:
    1.  config      config_option, load_config, ConfigMixin,
                    pydantic_config_option, versioned_pydantic_config_option
    2.  shell       shell_command, ShellMixin
    3.  progress    progress_command, progress_bar, spinner, track_progress
    4.  audit       audit_command, audit_command_async, register_audit_commands
    5.  i18n        MessageCatalog, set_locale, translate, I18nMixin
    6.  hooks       HookManager, ContextHookManager, NamedHookManager,
                    on_before, on_after, on_error, on_finally, wrap_command
    7.  cache       cached_command, CacheManager, temporary_cache,
                    register_cache_commands
    8.  middleware  use_middleware, Middleware (class-based), timing_middleware,
                    retry_middleware, logging_middleware, validate_middleware,
                    dry_run_middleware, logging_to_logger_middleware
    9.  plugins     PluginManager, register_plugin_commands
    10. wizard      WizardBuilder, Wizard, Step, quick_wizard
    11. templates   TemplateEngine, TemplateRepository, render_single_file
    12. migrations  MigrationManager, register_migration_commands
    +.  core        PowertyperApp, full_stack_command

Quick start:
    python complete_demo.py --help
    python complete_demo.py deploy --env production   # hooks+audit+middleware+config
    python complete_demo.py fast-deploy               # full_stack_command in one line
    python complete_demo.py fetch --source github     # cache + retry middleware
    python complete_demo.py serve --port 9090         # pydantic config
    python complete_demo.py process --count 15        # progress bar
    python complete_demo.py init                      # wizard
    python complete_demo.py quick-setup               # quick_wizard
    python complete_demo.py gen --name myproject      # template engine
    python complete_demo.py greet --name Alice --lang de  # i18n
    python complete_demo.py cache-demo                # CacheManager + temporary_cache
    python complete_demo.py shell                     # REPL
    python complete_demo.py audit history
    python complete_demo.py cache stats
    python complete_demo.py migrate list
    python complete_demo.py plugins list
"""

import logging
import textwrap
import time
from pathlib import Path
from typing import Optional

import typer

from pydantic import BaseModel
from rich.console import Console

from typer_powertools import (
    CacheManager,
    ConfigMixin,
    ContextHookManager,
    HookManager,
    MessageCatalog,
    Middleware,
    MigrationManager,
    NamedHookManager,
    PluginManager,
    TemplateEngine,
    WizardBuilder,
    audit_command,
    cached_command,
    config_option,
    configure_rich_logging,
    full_stack_command,
    load_config,
    logging_to_logger_middleware,
    on_before,
    on_finally,
    progress_bar,
    progress_command,
    pydantic_config_option,
    quick_wizard,
    register_audit_commands,
    register_cache_commands,
    register_migration_commands,
    register_plugin_commands,
    render_single_file,
    set_locale,
    shell_command,
    spinner,
    temporary_cache,
    track_progress,
)
from typer_powertools import translate as _
from typer_powertools import use_middleware

from typer_powertools.observability.middleware import (
    logging_middleware,
    retry_middleware,
    timing_middleware,
)

configure_rich_logging(level=logging.WARNING, log_time=False)
log = logging.getLogger("devkit")

console = Console()
DB_PATH = Path.home() / ".devkit_demo_audit.db"
CACHE_DIR = Path.home() / ".cache" / "devkit_demo"

# i18n: messages in English + German
catalog = MessageCatalog()
catalog.add_many(
    "en",
    {
        "deploy.help": "Deploy the service (hooks + audit + middleware + config).",
        "deploy.env": "Target environment.",
        "fetch.help": "Fetch remote data (cached for 60 s, with retry).",
        "fetch.source": "Data source name.",
        "process.help": "Process a batch of items (progress bar demo).",
        "process.count": "Number of items.",
        "init.help": "Interactive multi-step setup wizard.",
        "gen.help": "Generate a project from a Jinja2 template.",
        "gen.name": "Project name.",
        "greet.help": "Greet someone in their chosen language.",
        "greet.name": "Name of the person.",
        "greet.lang": "Language code (en | de).",
        "hello": "Hello, {name}! 👋",
        "serve.help": "Start server — demonstrates pydantic_config_option.",
    },
)
catalog.add_many(
    "de",
    {
        "deploy.help": "Dienst bereitstellen (Hooks + Audit + Middleware + Konfiguration).",
        "deploy.env": "Zielumgebung.",
        "fetch.help": "Remote-Daten abrufen (60 s gecacht, mit Wiederholung).",
        "fetch.source": "Name der Datenquelle.",
        "process.help": "Stapelverarbeitung (Fortschrittsbalken-Demo).",
        "process.count": "Anzahl der Elemente.",
        "init.help": "Interaktiver mehrstufiger Einrichtungsassistent.",
        "gen.help": "Projekt aus Jinja2-Vorlage generieren.",
        "gen.name": "Projektname.",
        "greet.help": "Jemanden in der gewählten Sprache begrüßen.",
        "greet.name": "Name der Person.",
        "greet.lang": "Sprachcode (en | de).",
        "hello": "Hallo, {name}! 👋",
        "serve.help": "Server starten — zeigt pydantic_config_option.",
    },
)
catalog.activate("en")

# migrations: define schema upgrades before the app is built
migration_manager = MigrationManager(app_name="devkit")


@migration_manager.migration("v1_to_v2", from_version="1.0", to_version="2.0")
def migrate_v1_to_v2(config: dict) -> dict:
    """Rename 'server' → 'host'."""
    if "server" in config:
        config["host"] = config.pop("server")
    return config


@migration_manager.migration("v2_to_v3", from_version="2.0", to_version="3.0")
def migrate_v2_to_v3(config: dict) -> dict:
    """Add 'timeout' with a default value."""
    config.setdefault("timeout", 30)
    return config


# hooks: HookManager with all four hook types
hooks = HookManager()


@hooks.before
def setup():
    """Runs before every @hooks.wrap command."""
    console.print("[dim]→ [hooks] before: acquiring resources[/dim]")


@hooks.after
def cleanup():
    """Runs after every successful @hooks.wrap command."""
    console.print("[dim]← [hooks] after:  releasing resources[/dim]")


@hooks.error
def handle_error(exc: Exception):
    """Runs when a @hooks.wrap command raises an exception."""
    console.print(f"[red]✗ [hooks] error: {exc}[/red]")


@hooks.finally_hook
def always_run():
    """Runs after every @hooks.wrap command, success or failure."""
    console.print("[dim]✔ [hooks] finally: always executed[/dim]")


# ContextHookManager: hooks that receive the command context
ctx_hooks = ContextHookManager()


@ctx_hooks.before_with_context
def log_invocation(context: dict):
    console.print(
        f"[dim]→ [ctx_hooks] calling '{context['command_name']}' "
        f"with args={context['args']} kwargs={context['kwargs']}[/dim]"
    )


@ctx_hooks.after_with_context
def log_result(context: dict, result):
    console.print(f"[dim]← [ctx_hooks] '{context['command_name']}' returned {result!r}[/dim]")


# NamedHookManager: per-command hooks
named_hooks = NamedHookManager()
named_hooks.for_command("_fetch_impl").before(
    lambda: console.print("[dim]→ [named_hooks] fetch starting[/dim]")
)

# module-level hook shortcuts (on_before / on_after / on_error / on_finally)
on_before(lambda: None)  # registered on the global default manager
on_finally(lambda: None)  # same – used to show the API exists


class EnvCheckMiddleware(Middleware):
    """Reject unknown environments before the command runs."""

    VALID_ENVS = {"staging", "production", "local"}

    def process(self, next_fn, *args, **kwargs):
        env = kwargs.get("env", "staging")
        if env not in self.VALID_ENVS:
            console.print(f"[red]✗ Unknown env '{env}'. Valid: {self.VALID_ENVS}[/red]")
            raise typer.Exit(code=1)
        return next_fn(*args, **kwargs)


# Pydantic config schema for `serve` command
class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8080
    debug: bool = False


app = typer.Typer(
    name="devkit",
    help="Complete typer-powertools demo — all 12 modules.",
    add_completion=False,
    rich_markup_mode="rich",
)


# deploy: config + hooks + audit + middleware + spinner
@app.command(help=_("deploy.help"))
@audit_command(app_name="devkit", db_path=DB_PATH)
@config_option(app_name="devkit", env_prefix="DEVKIT")
@hooks.wrap
@use_middleware(
    [
        timing_middleware(threshold_ms=0, verbose=True),  # always log timing
        logging_middleware(log_args=True, log_result=False),  # log invocation
        EnvCheckMiddleware(),  # class-based guard
    ]
)
def deploy(
    env: str = typer.Option("staging", help=_("deploy.env")),
    steps: int = typer.Option(4, "--steps", help="Number of deploy steps."),
):
    """
    [bold]Demonstrates:[/bold]
      [cyan]audit_command[/cyan]   — records invocation to SQLite
      [cyan]config_option[/cyan]   — reads from pyproject.toml / env vars / --config
      [cyan]hooks.wrap[/cyan]      — before / after / error / finally hooks
      [cyan]use_middleware[/cyan]  — timing + logging + class-based middleware chain
      [cyan]track_progress[/cyan]  — iterable-based progress bar
    """
    console.print(f"[bold]Deploying to {env}...[/bold]")
    for _ in track_progress(range(steps), description=f"Deploying to {env}…"):
        time.sleep(0.3)
    console.print(f"[green]✓ Deployed to {env}![/green]")


# fetch: cache + retry middleware + logging_to_logger_middleware
@app.command(help=_("fetch.help"))
@cached_command(ttl=60, app_name="devkit", cache_dir=CACHE_DIR)
@use_middleware(
    [
        retry_middleware(max_retries=2, delay=0.5, exponential_backoff=True),
        logging_to_logger_middleware(log_args=True, log_result=True),
    ]
)
def fetch(
    source: str = typer.Option("api", help=_("fetch.source")),
):
    """
    [bold]Demonstrates:[/bold]
      [cyan]cached_command[/cyan]              — result stored on disk, cache hit skips execution
      [cyan]retry_middleware[/cyan]            — retries on failure with exponential backoff
      [cyan]logging_to_logger_middleware[/cyan]— logs via Python logging (not Rich console)
    """
    with spinner(f"Fetching from {source}…"):
        time.sleep(1.5)
    console.print(f"[green]✓ Fetched data from {source}[/green]")
    return {"source": source, "records": [1, 2, 3, 4, 5]}


# process: progress_command generator + progress_bar
@app.command(help=_("process.help"))
@audit_command(app_name="devkit", db_path=DB_PATH)
@progress_command(description="Processing…", total_param="count")
def process(
    count: int = typer.Option(10, "--count", "-n", help=_("process.count")),
):
    """
    [bold]Demonstrates:[/bold]
      [cyan]progress_command[/cyan] — generator decorator; each yield = 1 step of progress
    """
    for _ in range(count):
        time.sleep(0.1)
        yield


@app.command()
def build(
    steps: int = typer.Option(6, "--steps", "-s", help="Build steps."),
):
    """
    [bold]Demonstrates:[/bold]
      [cyan]track_progress[/cyan] — iterable wrapper (like tqdm)
      [cyan]progress_bar[/cyan]   — context manager with manual advance(n) control
    """
    console.print("[bold]Phase 1 – compile[/bold]")
    for _ in track_progress(range(steps), description="Compiling…"):
        time.sleep(0.15)

    console.print("[bold]Phase 2 – link[/bold]")
    with progress_bar(total=steps, description="Linking…") as advance:
        for _ in range(steps):
            time.sleep(0.1)
            advance(1)

    console.print("[green]✓ Build complete![/green]")


# serve: pydantic_config_option (typed, validated config)
@app.command(help=_("serve.help"))
@pydantic_config_option(ServerConfig, app_name="devkit", inject_name="cfg")
def serve(
    cfg: ServerConfig,  # injected and validated from file/env/CLI
):
    """
    [bold]Demonstrates:[/bold]
      [cyan]pydantic_config_option[/cyan] — loads config, validates it into a Pydantic
        model, and injects it as a typed parameter. Adds --config / -c flag.
    """
    console.print(f"[bold]Server configuration:[/bold]")
    console.print(f"  host  = [cyan]{cfg.host}[/cyan]")
    console.print(f"  port  = [cyan]{cfg.port}[/cyan]")
    console.print(f"  debug = [cyan]{cfg.debug}[/cyan]")
    console.print(f"[green]✓ Server would start on {cfg.host}:{cfg.port}[/green]")


@app.command(name="fast-deploy")
@full_stack_command(
    "devkit",
    cache_ttl=120,
    progress_description="Fast deploying…",
)
def fast_deploy(
    env: str = typer.Option("staging", help="Target environment."),
):
    """
    [bold]Demonstrates:[/bold]
      [cyan]full_stack_command[/cyan] — bundles audit + cache + hooks + config +
        progress in a single decorator. The ultimate shortcut.
    """
    for _ in range(5):
        time.sleep(0.2)
        yield  # advances the progress bar


# greet: MessageCatalog, set_locale, translate with format args
@app.command(help=_("greet.help"))
def greet(
    name: str = typer.Option("World", "--name", "-n", help=_("greet.name")),
    lang: str = typer.Option("en", "--lang", "-l", help=_("greet.lang")),
):
    """
    [bold]Demonstrates:[/bold]
      [cyan]MessageCatalog.activate()[/cyan] — switch locale at runtime
      [cyan]translate() / _()[/cyan]          — look up a key with format args
      [cyan]MessageCatalog.locales()[/cyan]   — list registered locales
      [cyan]set_locale()[/cyan]               — module-level locale switch
    """
    catalog.activate(lang)
    message = _("hello", name=name)
    console.print(f"[bold cyan]{message}[/bold cyan]")
    console.print(f"[dim]locale: {lang} | available: {catalog.locales()}[/dim]")
    set_locale("en")  # restore default


# cache-demo: CacheManager directly + temporary_cache
@app.command(name="cache-demo")
def cache_demo():
    """
    [bold]Demonstrates:[/bold]
      [cyan]CacheManager[/cyan]   — direct key/value cache with TTL
      [cyan]temporary_cache[/cyan]— context manager cleared on exit
    """
    # Direct CacheManager usage
    cache = CacheManager(app_name="devkit", cache_dir=CACHE_DIR)
    cache.set("greeting", "hello from cache", ttl=60)
    value = cache.get("greeting")
    console.print(f"[green]CacheManager.get()[/green] → {value!r}")
    stats = cache.stats()
    console.print(
        f"[green]CacheManager.stats()[/green] → active={stats['active_entries']} "
        f"size={stats['total_size_bytes']} bytes"
    )

    # temporary_cache: cleared automatically when the block exits
    with temporary_cache(ttl=30, app_name="devkit-temp") as tmp:
        tmp.set("session_token", "abc123")
        token = tmp.get("session_token")
        console.print(f"[green]temporary_cache.get()[/green] → {token!r}")
    # tmp is fully cleared here
    console.print("[dim]temporary_cache cleared on exit[/dim]")


# init: full WizardBuilder with all step types
@app.command(help=_("init.help"))
def init():
    """
    [bold]Demonstrates:[/bold]
      [cyan]WizardBuilder[/cyan] — fluent API for multi-step interactive setup
        .ask()        — free-text input
        .choose()     — multiple-choice selection
        .ask_bool()   — yes/no confirmation
        .ask_int()    — integer input
        .ask_secret() — masked password input
        .build()      — returns a Wizard instance
    """
    wizard = (
        WizardBuilder("Devkit Setup")
        .ask("project_name", "Project name?", default="my-project")
        .choose("language", "Preferred language?", ["en", "de", "fr"])
        .ask_bool("caching", "Enable result caching?", default=True)
        .ask_int("timeout", "API timeout (seconds)?", default=30)
        .ask_secret("token", "API token (leave blank to skip):")
        .build()
    )
    answers = wizard.run()
    console.print("\n[green]✓ Setup complete![/green]")
    console.print(f"[dim]Saved: {answers}[/dim]")


# quick-setup: quick_wizard (minimal one-liner wizard)
@app.command(name="quick-setup")
def quick_setup():
    """
    [bold]Demonstrates:[/bold]
      [cyan]quick_wizard[/cyan] — one-line wizard for simple text questions
    """
    answers = quick_wizard(
        "Quick Setup",
        [
            ("name", "Your name?"),
            ("email", "Email address?"),
            ("region", "Preferred region?", "eu-west-1"),
        ],
    )
    console.print(f"\n[green]✓ Got answers:[/green] {answers}")


# gen: TemplateEngine (inline Jinja2 template)
@app.command(help=_("gen.help"))
def gen(
    name: str = typer.Argument(..., help=_("gen.name")),
    author: str = typer.Option("Anonymous", help="Project author."),
    language: str = typer.Option("python", help="Primary language."),
):
    """
    [bold]Demonstrates:[/bold]
      [cyan]TemplateEngine[/cyan]     — renders Jinja2 templates to an output directory
      [cyan]render_single_file[/cyan] — renders one template string to a file
    """
    import tempfile as _tmp

    with _tmp.TemporaryDirectory() as tmpdir:
        tpl_dir = Path(tmpdir) / "templates"
        out_dir = Path(tmpdir) / "output" / name
        tpl_dir.mkdir()

        # Write a simple Jinja2 template
        (tpl_dir / "README.md.j2").write_text(
            "# {{ project_name }}\n\nAuthor: {{ author }}\nLanguage: {{ language }}\n"
        )
        (tpl_dir / "main.py.j2").write_text(
            '"""{{ project_name }} — generated by devkit."""\n\n'
            "def main():\n    print('Hello from {{ project_name }}!')\n\n"
            "if __name__ == '__main__':\n    main()\n"
        )

        # TemplateEngine: renders a whole directory of templates
        engine = TemplateEngine(
            template_dir=tpl_dir,
            output_dir=out_dir,
            context={"project_name": name, "author": author, "language": language},
        )
        created = engine.render_all()

        console.print(f"\n[green]✓ Created {len(created)} file(s) for '{name}'[/green]")
        for f in created:
            console.print(f"  [cyan]{f.name}[/cyan]")
            console.print(f"[dim]{f.read_text()}[/dim]")

    # render_single_file: one-shot render from an ad-hoc template string
    import tempfile as _tmp2

    with _tmp2.NamedTemporaryFile(suffix=".py", delete=False, mode="w") as tpl_f:
        tpl_f.write("# {{ name }}'s entry point\nif __name__ == '__main__': pass\n")
        tpl_path = Path(tpl_f.name)

    out_path = Path(_tmp2.mktemp(suffix=".py"))
    result = render_single_file(tpl_path, out_path, context={"name": name}, overwrite=True)
    if result:
        console.print(f"[green]render_single_file →[/green] {result.name}")
        tpl_path.unlink(missing_ok=True)
        result.unlink(missing_ok=True)


# plugins: PluginManager with runtime-created plugin
import tempfile as _plugintmp

# Create a real plugin file at import time so the demo actually loads one
_plugin_dir = Path(_plugintmp.mkdtemp())
(_plugin_dir / "demo_hello.py").write_text(textwrap.dedent("""\
    \"\"\"A tiny demo plugin for devkit.\"\"\"

    import typer

    def register(app: typer.Typer) -> None:
        @app.command(name="hello-plugin")
        def hello():
            typer.echo("👋 Hello from the demo_hello plugin!")
"""))

plugins = PluginManager(app, plugin_prefix="demo_", entry_point_group="devkit.plugins")
plugins.discover_from_path(_plugin_dir)
plugins.load_all()
register_plugin_commands(app, plugins, command_group_name="plugins")


# shell: interactive REPL (all commands available inside)
shell_command(
    app,
    prompt="devkit> ",
    welcome_message="Welcome to devkit shell! Type 'help' to list commands.",
    history_file=str(Path.home() / ".devkit_history"),
)

# Register management sub-command groups
register_audit_commands(app, app_name="devkit", db_path=DB_PATH)
register_cache_commands(app, app_name="devkit", cache_dir=CACHE_DIR)
register_migration_commands(app, migration_manager, command_group_name="migrate")


# config-show: ConfigMixin (OOP style)
class DevkitConfig(ConfigMixin, app_name="devkit"):
    """ConfigMixin gives get_config() and show_config() as class methods."""


@app.command(name="config-show")
def config_show(
    config: Optional[Path] = typer.Option(None, "--config", "-c"),
):
    """
    [bold]Demonstrates:[/bold]
      [cyan]ConfigMixin.show_config()[/cyan] — pretty-prints the resolved config table
      [cyan]load_config()[/cyan]             — returns the raw merged dict
    """
    cfg = load_config(path=config, app_name="devkit")
    if not cfg:
        console.print(
            "[dim]No config found. Set [tool.devkit] in pyproject.toml "
            "or create config.yaml / config.json[/dim]"
        )
    else:
        DevkitConfig.show_config(path=config)


# NOTE – PowertyperApp builder (alternative to manual wiring above)
# The exact same app could be assembled with the fluent builder:
#
#   app = (
#       PowertyperApp("devkit")
#       .with_shell()
#       .with_audit(db_path="~/.devkit_audit.db")
#       .with_i18n(locale_dir="locales", default_locale="en")
#       .with_hooks()
#       .with_middleware()
#       .build()
#   )
#   # Then decorate commands normally.
#
# It auto-registers the shell, wraps all commands with audit, initializes
# i18n, and applies global hooks + middleware in one call.

if __name__ == "__main__":
    app()

"""
Focused demo of the 5 most essential modules.

  1. config   – Load settings from pyproject.toml / YAML / JSON / env vars
  2. progress – Spinners, progress bars, and track_progress
  3. audit    – Record every invocation to SQLite + view history
  4. i18n     – Multi-language help text with runtime locale switching
  5. shell    – Drop into an interactive REPL

Quick start:
    python core_features_demo.py --help
    python core_features_demo.py deploy --env production
    python core_features_demo.py deploy --env production --dry-run
    python core_features_demo.py process --count 20
    python core_features_demo.py build --steps 6
    python core_features_demo.py greet --name Alice --lang de
    python core_features_demo.py greet --name Marie --lang fr
    python core_features_demo.py config-show
    python core_features_demo.py audit history
    python core_features_demo.py audit stats
    python core_features_demo.py shell
"""

import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from typer_powertools import (
    MessageCatalog,
    audit_command,
    config_option,
    load_config,
    progress_bar,
    progress_command,
    register_audit_commands,
    set_locale,
    shell_command,
    spinner,
    track_progress,
)
from typer_powertools import translate as _

console = Console()

# i18n: Define messages in three languages up front.
# MessageCatalog holds translations in memory; call .activate() to switch.
# The global translate() / _() function looks up the active catalog.
catalog = MessageCatalog()

catalog.add_many(
    "en",
    {
        "app.help": "Core features demo powered by typer-powertools.",
        "deploy.help": "Deploy the application to a target environment.",
        "deploy.env": "Target environment (staging | production).",
        "deploy.dry": "Simulate without making any real changes.",
        "process.help": "Process a batch of items with a live progress bar.",
        "process.count": "Number of items to process.",
        "greet.help": "Greet someone in their chosen language.",
        "greet.name": "Name of the person to greet.",
        "greet.lang": "Language code: en, de, or fr.",
        "hello": "Hello, {name}! Welcome to myapp.",
    },
)
catalog.add_many(
    "de",
    {
        "app.help": "Core-Features-Demo mit typer-powertools.",
        "deploy.help": "Anwendung in der Zielumgebung bereitstellen.",
        "deploy.env": "Zielumgebung (staging | production).",
        "deploy.dry": "Bereitstellung simulieren, ohne Änderungen vorzunehmen.",
        "process.help": "Stapelverarbeitung mit Fortschrittsbalken.",
        "process.count": "Anzahl der zu verarbeitenden Elemente.",
        "greet.help": "Jemanden in der gewählten Sprache begrüßen.",
        "greet.name": "Name der zu begrüßenden Person.",
        "greet.lang": "Sprachcode: en, de oder fr.",
        "hello": "Hallo, {name}! Willkommen bei myapp.",
    },
)
catalog.add_many(
    "fr",
    {
        "app.help": "Démo des fonctionnalités principales avec typer-powertools.",
        "deploy.help": "Déployer l'application dans l'environnement cible.",
        "deploy.env": "Environnement cible (staging | production).",
        "deploy.dry": "Simuler le déploiement sans effectuer de changements.",
        "process.help": "Traiter un lot d'éléments avec une barre de progression.",
        "process.count": "Nombre d'éléments à traiter.",
        "greet.help": "Saluer quelqu'un dans sa langue.",
        "greet.name": "Nom de la personne à saluer.",
        "greet.lang": "Code de langue : en, de ou fr.",
        "hello": "Bonjour, {name}! Bienvenue dans myapp.",
    },
)
catalog.activate("en")

app = typer.Typer(
    name="myapp",
    help=_("app.help"),
    add_completion=False,
    rich_markup_mode="rich",
)

# SQLite file for audit records
DB_PATH = Path.home() / ".myapp_demo_audit.db"


# config + audit + spinner
@app.command(help=_("deploy.help"))
@audit_command(app_name="myapp-demo", db_path=DB_PATH)
#   ↑ records: timestamp, user, env, dry_run, exit_code, duration_ms to SQLite
@config_option(app_name="myapp", env_prefix="MYAPP")
#   ↑ merges config from: CLI args > MYAPP_* env vars > pyproject.toml [tool.myapp]
#     also adds a --config / -c flag to point at any .toml/.yaml/.json file
def deploy(
    env: str = typer.Option("staging", help=_("deploy.env")),
    dry_run: bool = typer.Option(False, "--dry-run", help=_("deploy.dry")),
):
    """Deploy with [cyan]config_option[/cyan] + [cyan]audit_command[/cyan] + [cyan]spinner[/cyan]."""
    if dry_run:
        console.print(f"[yellow]DRY RUN[/yellow] → would deploy to [bold]{env}[/bold]")
        return

    # spinner: Rich animated status while blocking work runs
    with spinner(f"Deploying to [bold]{env}[/bold]…"):
        time.sleep(2)

    console.print(f"[green]✓[/green] Deployed to [bold]{env}[/bold]!")


# progress_command (generator pattern → determinate bar)
@app.command(help=_("process.help"))
@audit_command(app_name="myapp-demo", db_path=DB_PATH)
@progress_command(description="Processing items…", total_param="count")
#   ↑ wraps a generator; each `yield` advances the bar by 1.
#     when total_param is given, shows a determinate bar with ETA.
def process(
    count: int = typer.Option(10, "--count", "-n", help=_("process.count")),
):
    """Process items with [cyan]progress_command[/cyan] generator pattern."""
    for _ in range(count):
        time.sleep(0.1)
        yield  # ← one yield = one step of progress


# track_progress (iterable) + progress_bar (manual advance)
@app.command()
def build(
    steps: int = typer.Option(8, "--steps", "-s", help="Number of build steps."),
):
    """Show [cyan]track_progress[/cyan] and [cyan]progress_bar[/cyan] context manager."""
    # track_progress: wraps any iterable, similar to tqdm
    console.print("[bold]Phase 1 – compile[/bold]")
    for _ in track_progress(range(steps), description="Compiling…"):
        time.sleep(0.15)

    # progress_bar: context manager yielding an advance(n) callable
    console.print("[bold]Phase 2 – link[/bold]")
    with progress_bar(total=steps, description="Linking…") as advance:
        for _ in range(steps):
            time.sleep(0.1)
            advance(1)  # manually advance by 1

    console.print("[green]✓ Build complete![/green]")


# i18n: runtime locale switch, format args, available locales
@app.command(help=_("greet.help"))
@audit_command(app_name="myapp-demo", db_path=DB_PATH)
def greet(
    name: str = typer.Option("World", "--name", "-n", help=_("greet.name")),
    lang: str = typer.Option("en", "--lang", "-l", help=_("greet.lang")),
):
    """Greet in any language — shows [cyan]MessageCatalog.activate()[/cyan] + [cyan]translate()[/cyan]."""
    catalog.activate(lang)  # switch locale at runtime
    message = _("hello", name=name)  # translate with format args
    console.print(f"[bold cyan]{message}[/bold cyan]")
    console.print(f"[dim]locale: {lang}  |  available: {catalog.locales()}[/dim]")

    # set_locale() is the module-level alternative (no catalog object needed)
    set_locale("en")  # restore default


# config: load_config() standalone (no decorator)
@app.command(name="config-show")
def config_show(
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Explicit config file path. Auto-detected if omitted.",
    ),
):
    """Show the resolved configuration with [cyan]load_config()[/cyan]."""
    cfg = load_config(path=config, app_name="myapp")
    if not cfg:
        console.print("[dim]No config file found — using defaults.[/dim]")
        console.print("[dim]Tip: create pyproject.toml with [tool.myapp] section,[/dim]")
        console.print("[dim]     config.yaml, or set MYAPP_* env vars.[/dim]")
    else:
        console.print("[bold]Resolved configuration:[/bold]")
        for k, v in cfg.items():
            console.print(f"  [cyan]{k}[/cyan] = [green]{v!r}[/green]")


# shell: interactive REPL
# shell_command() registers a `shell` sub-command that drops into a REPL
# where users can run any of the commands above without re-invoking the script.
shell_command(
    app,
    prompt="myapp> ",
    welcome_message="Welcome to myapp shell! Type 'help' to list commands, 'exit' to quit.",
    history_file=str(Path.home() / ".myapp_history"),
)

# audit: add history / stats / clear sub-commands
register_audit_commands(app, app_name="myapp-demo", db_path=DB_PATH)
# ↑ registers:  myapp audit history [--limit N] [--command CMD]
#               myapp audit stats
#               myapp audit clear [--yes]


if __name__ == "__main__":
    app()

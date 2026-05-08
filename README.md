# typer-powertools

> **Extended batteries for Typer** — 12 powerful CLI extensions to build production-grade tools faster.

[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-172%20passed-success.svg)](TEST_COVERAGE.md)

**typer-powertools** extends [Typer](https://typer.tiangolo.com/) with the features every professional CLI eventually needs: layered configuration, auditing, interactive shells, setup wizards, and more. Stop writing boilerplate and start building features.

---

## 12 Batteries Included

| Module | Description |
| :--- | :--- |
| **config** | Layered settings (pyproject.toml, .env, YAML, JSON) with Pydantic validation. |
| **shell** | Turn your multi-command app into an interactive REPL with history and help. |
| **progress** | Declarative progress bars, spinners, and task tracking via Rich. |
| **audit** | Transparent SQLite-backed logging of every command invocation and result. |
| **i18n** | Internationalization for help text and messages (files or in-memory). |
| **hooks** | Lifecycle hooks (before, after, error, finally) for setup and teardown. |
| **cache** | TTL-based result caching for expensive API calls or heavy computations. |
| **middleware** | Request/response pipeline for authentication, timing, retries, and more. |
| **plugins** | Dynamic plugin discovery from paths or installed Python packages. |
| **wizard** | Interactive multi-step setup wizards with validation and conditional logic. |
| **templates** | Project and file generation using Jinja2 templates. |
| **migrations** | Versioning and automatic migration of user configuration files. |

---

## Quick Start

```python
import typer
from typer_powertools import config_option, audit_command, cached_command, track_progress

app = typer.Typer()

@app.command()
@audit_command(app_name="myapp")  # ← Logs invocation to SQLite
@cached_command(ttl=3600)         # ← Caches result for 1 hour
@config_option(app_name="myapp")  # ← Loads from pyproject.toml / .env
def deploy(env: str = "staging"):
    for step in track_progress(range(10), description="Deploying..."):
        do_work(step)
    typer.echo(f"✓ Deployed to {env}")

if __name__ == "__main__":
    app()
```

---

## Feature Highlights

### 🛠 Layered Config & Pydantic
Automatically load configuration from multiple sources with strict precedence: CLI args > Env Vars > Config File > Defaults.

```python
from typer_powertools import pydantic_config_option
from pydantic import BaseModel

class MyConfig(BaseModel):
    api_key: str
    timeout: int = 30

@app.command()
@pydantic_config_option(MyConfig, app_name="myapp")
def connect(cfg: MyConfig):
    typer.echo(f"Connecting with {cfg.api_key}...")
```

### 🐚 Interactive Shell (REPL)
Give your users a powerful interactive environment with one line of code.

```python
from typer_powertools import shell_command

# Registers a 'shell' command to your app
shell_command(app, prompt="myapp> ")
```

### 🕵️‍♂️ Transparent Auditing
Keep a permanent record of what your CLI did. Includes management commands to view history and stats.

```python
from typer_powertools import register_audit_commands

@app.command()
@audit_command(app_name="myapp", sensitive_params=["password"])
def login(password: str):
    pass

register_audit_commands(app, app_name="myapp")
# Adds: myapp audit history / myapp audit stats
```

### 🧙‍♂️ Setup Wizards
Build complex interactive configurations with a fluent API.

```python
from typer_powertools import WizardBuilder

@app.command()
def init():
    wizard = (
        WizardBuilder("Initial Setup")
        .ask("name", "Project Name?")
        .choose("theme", "Select Theme", ["dark", "light"])
        .ask_secret("key", "API Key")
        .build()
    )
    results = wizard.run()
    typer.echo(f"Setup complete for {results['name']}!")
```

### 🔄 Config Migrations
Evolve your configuration schema without breaking your users' setups.

```python
from typer_powertools import MigrationManager, register_migration_commands

manager = MigrationManager("myapp")

@manager.migration("v1_to_v2", from_version="1.0", to_version="2.0")
def upgrade(config):
    config["new_key"] = config.pop("old_key")
    return config

register_migration_commands(app, manager)
```

---

## Installation

```bash
# Install core
pip install typer-powertools

# Install with optional features
pip install "typer-powertools[cache]"      # For TTL caching
pip install "typer-powertools[templates]"  # For Jinja2 templates
pip install "typer-powertools[all]"        # Install everything
```

---

## Documentation & Learning

- **[Quick Reference](QUICKREF.md)** — The ultimate cheat sheet for every API.

---

## Examples

Check out the `examples/` directory for complete applications:
- [`core_features_demo.py`](examples/core_features_demo.py) — Core features in action.
- [`complete_demo.py`](examples/complete_demo.py) — A massive CLI using all 12 modules.

---

## License

Built by Muhammad Ali. Distributed under the **Apache License 2.0**. See `LICENSE` for more information.

*Built on top of [Typer](https://typer.tiangolo.com/) and [Rich](https://rich.readthedocs.io/).*

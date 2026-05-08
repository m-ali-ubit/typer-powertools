import json

import pytest
import typer
from typer.testing import CliRunner

from typer_powertools.config.loader import _load_env_vars, config_option
from typer_powertools.config.schema import (
    pydantic_config_option,
    versioned_pydantic_config_option,
)
from typer_powertools.migrations.manager import MigrationManager

try:
    from pydantic import BaseModel

    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False

runner = CliRunner()


def test_config_explicit_cli(tmp_path):
    app = typer.Typer()

    @app.command()
    @config_option(app_name="myapp")
    def run(port: int = 8000, host: str = "localhost"):
        typer.echo(f"{host}:{port}")

    res = runner.invoke(app, ["--port", "8000", "--host", "127.0.0.1"])
    assert res.exit_code == 0
    assert "127.0.0.1:8000" in res.stdout


def test_feature_env_support(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    with open(env_file, "w") as f:
        f.write("MYAPP_PORT=9090\n")
        f.write("MYAPP_HOST=0.0.0.0\n")

    monkeypatch.delenv("MYAPP_PORT", raising=False)
    res = _load_env_vars(prefix="MYAPP", keys=["port", "host"], env_file=str(env_file))

    try:
        import dotenv

        assert res["port"] == 9090
        assert res["host"] == "0.0.0.0"
    except ImportError:
        pass


@pytest.mark.skipif(not HAS_PYDANTIC, reason="Pydantic not installed")
def test_feature_pydantic_config(tmp_path):
    class MyConfig(BaseModel):
        timeout: int = 30
        mode: str = "prod"

    app = typer.Typer()

    @app.command()
    @pydantic_config_option(MyConfig, app_name="myapp")
    def run(cfg: MyConfig):
        typer.echo(f"{cfg.timeout}-{cfg.mode}")

    # Standard invoke falling back to defaults (no config file or env)
    res = runner.invoke(app, [])
    assert res.exit_code == 0
    assert "30-prod" in res.stdout


@pytest.mark.skipif(not HAS_PYDANTIC, reason="Pydantic not installed")
def test_feature_versioned_pydantic_config(tmp_path, monkeypatch):
    class MyConfig(BaseModel):
        value: str = "default"
        flag: bool = False

    # Prepare a v1 config on disk
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"_version": "1.0", "old_value": "from_file", "flag": False}))

    # Define migrations to bring it to v2.0 and rename the key
    manager = MigrationManager(app_name="myapp")

    @manager.migration("v1_to_v2", from_version="1.0", to_version="2.0")
    def v1_to_v2(config: dict) -> dict:
        config["value"] = config.pop("old_value")
        return config

    app = typer.Typer()

    @app.command()
    @versioned_pydantic_config_option(
        MyConfig,
        manager=manager,
        app_name="myapp",
        to_version="2.0",
    )
    def run(cfg: MyConfig):
        typer.echo(f"{cfg.value}-{cfg.flag}")

    # Invoke with explicit --config path so the manager updates the file on disk
    res = runner.invoke(app, ["--config", str(cfg_path)])
    assert res.exit_code == 0
    # The value should come from the migrated config (old_value -> value)
    assert "from_file-False" in res.stdout

    # The file on disk should now advertise the new version
    updated = json.loads(cfg_path.read_text())
    assert updated["_version"] == "2.0"

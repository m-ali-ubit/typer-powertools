from __future__ import annotations

import json
import logging

import pytest
import typer
from typer.testing import CliRunner

from typer_powertools import full_stack_command
from typer_powertools.observability.logging import (
    configure_rich_logging,
    logging_to_logger_middleware,
)
from typer_powertools.observability.middleware import use_middleware
from typer_powertools.testing import run_cli, temp_config_file

runner = CliRunner()


def test_full_stack_command_basic():
    app = typer.Typer()

    @app.command()
    @full_stack_command("testapp", cache_ttl=60)
    def deploy(env: str = "staging"):
        typer.echo(f"deployed-{env}")

    res = runner.invoke(app, ["--env", "prod"])
    assert res.exit_code == 0
    assert "deployed-prod" in res.stdout


def test_full_stack_command_with_middleware():
    app = typer.Typer()

    @app.command()
    @full_stack_command("testapp", middleware=[logging_to_logger_middleware(log_args=False)])
    def status():
        typer.echo("ok")

    res = runner.invoke(app, [])
    assert res.exit_code == 0
    assert "ok" in res.stdout


def test_configure_rich_logging():
    from rich.logging import RichHandler

    root = logging.getLogger()
    try:
        configure_rich_logging(logging.DEBUG, log_time=False, log_path=False)
        assert any(isinstance(h, RichHandler) for h in root.handlers)
    finally:
        # Remove handlers added by configure_rich_logging (it uses basicConfig)
        root.handlers = [h for h in root.handlers if not isinstance(h, RichHandler)]


def test_logging_to_logger_middleware_integration():
    log_capture: list[str] = []

    class CaptureHandler(logging.Handler):
        def emit(self, record):
            log_capture.append(self.format(record))

    logger = logging.getLogger("test_middleware")
    logger.setLevel(logging.INFO)
    handler = CaptureHandler()
    logger.addHandler(handler)
    try:
        app = typer.Typer()

        @app.command()
        @use_middleware([logging_to_logger_middleware(logger=logger, log_args=True)])
        def hello(name: str = "world"):
            typer.echo(f"Hello, {name}")

        res = runner.invoke(app, ["--name", "tests"])
        assert res.exit_code == 0
        assert "Hello, tests" in res.stdout
        assert any("hello" in m.lower() for m in log_capture)
    finally:
        logger.removeHandler(handler)


def test_run_cli():
    app = typer.Typer()

    @app.command()
    def ping():
        typer.echo("pong")

    result = run_cli(app, [])
    assert result.exit_code == 0
    assert "pong" in result.stdout


def test_temp_config_file(tmp_path):
    data = {"key": "value", "n": 42}
    with temp_config_file(data, directory=tmp_path) as path:
        assert path.exists()
        assert path.suffix == ".json"
        loaded = json.loads(path.read_text())
        assert loaded == data
    assert not path.exists()


def test_temp_config_file_cleanup_on_error(tmp_path):
    path_holder = []

    with pytest.raises(ValueError):
        with temp_config_file({"a": 1}, directory=tmp_path) as path:
            path_holder.append(path)
            raise ValueError("oops")
    assert path_holder
    assert not path_holder[0].exists()

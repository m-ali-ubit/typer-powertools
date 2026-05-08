from __future__ import annotations

import json

import pytest
import typer
from typer.testing import CliRunner

from typer_powertools.config.loader import _coerce, _load_env_vars, load_config
from typer_powertools.i18n.catalog import (
    MessageCatalog,
    _detect_locale,
    init,
    set_locale,
    translate,
)
from typer_powertools.input.progress import progress_command, track_progress
from typer_powertools.observability.audit import (
    _get_connection,
    _record,
    audit_command,
    register_audit_commands,
)


class TestCoerce:
    def test_bool_true(self):
        assert _coerce("true") is True
        assert _coerce("yes") is True
        assert _coerce("1") is True

    def test_bool_false(self):
        assert _coerce("false") is False
        assert _coerce("no") is False
        assert _coerce("0") is False

    def test_int(self):
        assert _coerce("42") == 42

    def test_float(self):
        assert _coerce("3.14") == pytest.approx(3.14)

    def test_string(self):
        assert _coerce("hello") == "hello"


class TestLoadEnvVars:
    def test_reads_matching_env_vars(self, monkeypatch):
        monkeypatch.setenv("MYAPP_OUTPUT", "dist")
        monkeypatch.setenv("MYAPP_VERBOSE", "true")
        result = _load_env_vars("MYAPP", ["output", "verbose"])
        assert result["output"] == "dist"
        assert result["verbose"] is True

    def test_ignores_unrelated_vars(self, monkeypatch):
        monkeypatch.setenv("OTHER_OUTPUT", "dist")
        result = _load_env_vars("MYAPP", ["output"])
        assert "output" not in result


class TestLoadConfigJson:
    def test_loads_json_config(self, tmp_path):
        cfg = {"output": "build", "verbose": True}
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps(cfg))
        result = load_config(path=cfg_file)
        assert result["output"] == "build"
        assert result["verbose"] is True

    def test_returns_empty_for_missing_file(self, tmp_path):
        # No config files in temp dir — should return {}
        result = load_config(path=None, app_name="nonexistent", search_parents=False)
        assert result == {}


class TestLoadConfigToml:
    def test_loads_toml_config(self, tmp_path):
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text('output = "release"\nverbose = false\n')
        result = load_config(path=cfg_file)
        assert result["output"] == "release"
        assert result["verbose"] is False

    def test_pyproject_toml_with_app_name(self, tmp_path):
        content = '[tool.myapp]\noutput = "dist"\n'
        (tmp_path / "pyproject.toml").write_text(content)
        result = load_config(path=tmp_path / "pyproject.toml", app_name="myapp")
        assert result["output"] == "dist"


class TestTrackProgress:
    def test_returns_all_items(self):
        items = list(range(5))
        result = list(track_progress(items, description="test", transient=True))
        assert result == items

    def test_works_with_generator(self):
        def gen():
            yield from range(3)

        result = list(track_progress(gen(), description="gen", total=3, transient=True))
        assert result == [0, 1, 2]


class TestProgressCommandDecorator:
    def test_non_generator_runs(self):
        runner = CliRunner()
        app = typer.Typer()

        @app.command()
        @progress_command(description="Doing work…")
        def work():
            pass  # non-generator

        result = runner.invoke(app)
        assert result.exit_code == 0

    def test_generator_with_total(self):
        runner = CliRunner()
        app = typer.Typer()

        @app.command()
        @progress_command(description="Items…", total_param="count")
        def process(count: int = 3):
            for _ in range(count):
                yield

        result = runner.invoke(app, ["--count", "3"])
        assert result.exit_code == 0


class TestAuditRecord:
    def test_records_entry(self, tmp_path):
        db = tmp_path / "audit.db"
        _record(db, "deploy", {"env": "staging"}, 0, 42.0)
        conn = _get_connection(db)
        rows = conn.execute("SELECT * FROM audit_log").fetchall()
        assert len(rows) == 1
        assert rows[0]["command"] == "deploy"
        assert rows[0]["exit_code"] == 0
        conn.close()

    def test_records_failure(self, tmp_path):
        db = tmp_path / "audit.db"
        _record(db, "deploy", {}, 1, 10.0)
        conn = _get_connection(db)
        row = conn.execute("SELECT * FROM audit_log").fetchone()
        assert row["exit_code"] == 1
        conn.close()


class TestAuditDecorator:
    def test_command_still_runs(self, tmp_path):
        runner = CliRunner()
        app = typer.Typer()
        db = tmp_path / "audit.db"

        @app.command()
        @audit_command(app_name="test", db_path=db)
        def ping(host: str = "localhost"):
            typer.echo(f"pong {host}")

        result = runner.invoke(app, ["--host", "example.com"])
        assert result.exit_code == 0
        assert "pong example.com" in result.output

    def test_entry_written(self, tmp_path):
        runner = CliRunner()
        app = typer.Typer()
        db = tmp_path / "audit.db"

        @app.command()
        @audit_command(app_name="test", db_path=db)
        def ping(host: str = "localhost"):
            pass

        runner.invoke(app)
        conn = _get_connection(db)
        rows = conn.execute("SELECT * FROM audit_log").fetchall()
        assert len(rows) == 1
        conn.close()

    def test_sensitive_params_redacted(self, tmp_path):
        runner = CliRunner()
        app = typer.Typer()
        db = tmp_path / "audit.db"

        @app.command()
        @audit_command(app_name="test", db_path=db, sensitive_params=["token"])
        def login(token: str = "secret123"):
            pass

        runner.invoke(app, ["--token", "supersecret"])
        conn = _get_connection(db)
        row = conn.execute("SELECT args FROM audit_log").fetchone()
        args = json.loads(row["args"])
        assert args["token"] == "***"
        conn.close()


class TestRegisterAuditCommands:
    def test_history_command_exists(self, tmp_path):
        runner = CliRunner()
        app = typer.Typer()
        db = tmp_path / "audit.db"
        register_audit_commands(app, app_name="test", db_path=db)
        result = runner.invoke(app, ["audit", "history"])
        assert result.exit_code == 0

    def test_stats_command_exists(self, tmp_path):
        runner = CliRunner()
        app = typer.Typer()
        db = tmp_path / "audit.db"
        register_audit_commands(app, app_name="test", db_path=db)
        result = runner.invoke(app, ["audit", "stats"])
        assert result.exit_code == 0

    def test_clear_with_yes_flag(self, tmp_path):
        runner = CliRunner()
        app = typer.Typer()
        db = tmp_path / "audit.db"
        _record(db, "cmd", {}, 0, 1.0)
        register_audit_commands(app, app_name="test", db_path=db)
        result = runner.invoke(app, ["audit", "clear", "--yes"])
        assert result.exit_code == 0
        conn = _get_connection(db)
        count = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        assert count == 0
        conn.close()


class TestTranslate:
    def setup_method(self):
        # Reset to English with empty catalog
        set_locale("en")

    def test_returns_key_when_no_catalog(self):
        assert translate("missing.key") == "missing.key"

    def test_format_substitution(self, tmp_path):
        (tmp_path / "en.json").write_text(json.dumps({"greet": "Hello, {name}!"}))
        init(tmp_path, locale="en", auto_detect=False)
        assert translate("greet", name="Alice") == "Hello, Alice!"

    def test_locale_switch(self, tmp_path):
        (tmp_path / "en.json").write_text(json.dumps({"greet": "Hello!"}))
        (tmp_path / "de.json").write_text(json.dumps({"greet": "Hallo!"}))
        init(tmp_path, locale="en", auto_detect=False)
        assert translate("greet") == "Hello!"
        set_locale("de")
        assert translate("greet") == "Hallo!"

    def test_fallback_to_english(self, tmp_path):
        (tmp_path / "en.json").write_text(json.dumps({"fallback_msg": "Only in English"}))
        (tmp_path / "fr.json").write_text(json.dumps({}))
        init(tmp_path, locale="en", auto_detect=False)
        set_locale("fr")
        assert translate("fallback_msg") == "Only in English"


class TestMessageCatalog:
    def test_add_and_translate(self):
        cat = MessageCatalog()
        cat.add("en", "hello", "Hello!")
        cat.add("de", "hello", "Hallo!")
        cat.activate("de")
        assert translate("hello") == "Hallo!"

    def test_add_many(self):
        cat = MessageCatalog()
        cat.add_many("en", {"a": "A", "b": "B"})
        cat.activate("en")
        assert translate("a") == "A"
        assert translate("b") == "B"

    def test_locales_list(self):
        cat = MessageCatalog()
        cat.add("en", "k", "v")
        cat.add("de", "k", "v")
        assert set(cat.locales()) == {"en", "de"}


class TestDetectLocale:
    def test_detects_from_lang_env(self, monkeypatch):
        monkeypatch.setenv("LANG", "de_DE.UTF-8")
        monkeypatch.delenv("LANGUAGE", raising=False)
        monkeypatch.delenv("LC_ALL", raising=False)
        monkeypatch.delenv("LC_MESSAGES", raising=False)
        assert _detect_locale() == "de"

    def test_defaults_to_en(self, monkeypatch):
        for var in ("LANGUAGE", "LANG", "LC_ALL", "LC_MESSAGES"):
            monkeypatch.delenv(var, raising=False)
        assert _detect_locale() == "en"

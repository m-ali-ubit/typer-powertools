import json

import pytest
import typer
from typer.testing import CliRunner

from typer_powertools.config.loader import (
    ConfigMixin,
    _coerce,
    _load_env_vars,
    _parse_json,
    _parse_toml,
    config_option,
    load_config,
)


class TestCoerce:
    def test_bool_true_variations(self):
        assert _coerce("true") is True
        assert _coerce("True") is True
        assert _coerce("TRUE") is True
        assert _coerce("yes") is True
        assert _coerce("Yes") is True
        assert _coerce("1") is True

    def test_bool_false_variations(self):
        assert _coerce("false") is False
        assert _coerce("False") is False
        assert _coerce("FALSE") is False
        assert _coerce("no") is False
        assert _coerce("No") is False
        assert _coerce("0") is False

    def test_integer_coercion(self):
        assert _coerce("42") == 42
        assert _coerce("-10") == -10
        assert _coerce("0") == 0

    def test_float_coercion(self):
        assert _coerce("3.14") == pytest.approx(3.14)
        assert _coerce("-2.5") == pytest.approx(-2.5)
        assert _coerce("0.0") == pytest.approx(0.0)

    def test_string_fallback(self):
        assert _coerce("hello") == "hello"
        assert _coerce("not-a-number") == "not-a-number"
        assert _coerce("") == ""

    def test_edge_cases(self):
        # Mixed case strings that aren't bool
        assert _coerce("TrUe") == "TrUe"
        assert _coerce("yEs") == "yEs"
        # Numbers with spaces (should remain strings)
        assert _coerce(" 42 ") == " 42 "


class TestLoadEnvVars:
    def test_reads_matching_vars(self, monkeypatch):
        monkeypatch.setenv("MYAPP_OUTPUT", "dist")
        monkeypatch.setenv("MYAPP_VERBOSE", "true")
        monkeypatch.setenv("MYAPP_PORT", "8080")

        result = _load_env_vars("MYAPP", ["output", "verbose", "port"])

        assert result["output"] == "dist"
        assert result["verbose"] is True
        assert result["port"] == 8080

    def test_handles_underscores_in_keys(self, monkeypatch):
        monkeypatch.setenv("APP_DATABASE_URL", "postgres://...")
        result = _load_env_vars("APP", ["database_url"])
        assert result["database_url"] == "postgres://..."

    def test_handles_hyphens_in_keys(self, monkeypatch):
        monkeypatch.setenv("APP_LOG_LEVEL", "debug")
        result = _load_env_vars("APP", ["log-level"])
        assert result["log-level"] == "debug"

    def test_ignores_unrelated_vars(self, monkeypatch):
        monkeypatch.setenv("OTHER_VAR", "value")
        monkeypatch.setenv("MYAPP_OUTPUT", "dist")

        result = _load_env_vars("MYAPP", ["output", "other"])

        assert "output" in result
        assert "other" not in result

    def test_empty_keys_list(self, monkeypatch):
        monkeypatch.setenv("APP_VAR", "value")
        result = _load_env_vars("APP", [])
        assert result == {}

    def test_prefix_trailing_underscore(self, monkeypatch):
        monkeypatch.setenv("APP_VAR", "value")
        result = _load_env_vars("APP_", ["var"])
        assert result["var"] == "value"


class TestParseJson:
    def test_parse_flat_json(self, tmp_path):
        config = {"output": "dist", "verbose": True, "count": 42}
        path = tmp_path / "config.json"
        path.write_text(json.dumps(config))

        result = _parse_json(path, app_name=None)
        assert result == config

    def test_parse_nested_json_with_app_name(self, tmp_path):
        config = {"myapp": {"output": "dist", "verbose": True}, "other": {"key": "value"}}
        path = tmp_path / "config.json"
        path.write_text(json.dumps(config))

        result = _parse_json(path, app_name="myapp")
        assert result == {"output": "dist", "verbose": True}

    def test_parse_json_without_app_section(self, tmp_path):
        config = {"output": "dist"}
        path = tmp_path / "config.json"
        path.write_text(json.dumps(config))

        result = _parse_json(path, app_name="myapp")
        assert result == {"output": "dist"}

    def test_invalid_json(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{ invalid json }")

        with pytest.raises(json.JSONDecodeError):
            _parse_json(path, app_name=None)

    def test_empty_json(self, tmp_path):
        path = tmp_path / "empty.json"
        path.write_text("{}")

        result = _parse_json(path, app_name=None)
        assert result == {}


class TestParseToml:
    def test_parse_simple_toml(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text('output = "dist"\nverbose = true\ncount = 42')

        result = _parse_toml(path, app_name=None)
        assert result["output"] == "dist"
        assert result["verbose"] is True
        assert result["count"] == 42

    def test_parse_pyproject_toml(self, tmp_path):
        path = tmp_path / "pyproject.toml"
        path.write_text('[tool.myapp]\noutput = "release"\nverbose = false')

        result = _parse_toml(path, app_name="myapp")
        assert result["output"] == "release"
        assert result["verbose"] is False

    def test_pyproject_without_tool_section(self, tmp_path):
        path = tmp_path / "pyproject.toml"
        path.write_text('[build-system]\nrequires = ["setuptools"]')

        result = _parse_toml(path, app_name="myapp")
        assert result == {}

    def test_pyproject_with_wrong_app_name(self, tmp_path):
        path = tmp_path / "pyproject.toml"
        path.write_text('[tool.otherapp]\nkey = "value"')

        result = _parse_toml(path, app_name="myapp")
        assert result == {}

    def test_invalid_toml(self, tmp_path):
        path = tmp_path / "bad.toml"
        path.write_text("invalid toml [[[")

        with pytest.raises(Exception):  # tomllib.TOMLDecodeError
            _parse_toml(path, app_name=None)


class TestLoadConfig:
    def test_explicit_path_json(self, tmp_path):
        config = {"key": "value"}
        path = tmp_path / "config.json"
        path.write_text(json.dumps(config))

        result = load_config(path=path)
        assert result == config

    def test_explicit_path_toml(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text('key = "value"')

        result = load_config(path=path)
        assert result["key"] == "value"

    def test_auto_search_pyproject_toml(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        path = tmp_path / "pyproject.toml"
        path.write_text('[tool.myapp]\nkey = "found"')

        result = load_config(app_name="myapp", search_parents=False)
        assert result["key"] == "found"

    def test_auto_search_config_toml(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        path = tmp_path / "config.toml"
        path.write_text('key = "value"')

        result = load_config(search_parents=False)
        assert result["key"] == "value"

    def test_returns_empty_when_no_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = load_config(search_parents=False)
        assert result == {}

    def test_search_parents(self, tmp_path, monkeypatch):
        parent = tmp_path
        child = parent / "subdir"
        child.mkdir()

        config_path = parent / "config.toml"
        config_path.write_text('key = "parent"')

        monkeypatch.chdir(child)
        result = load_config(search_parents=True)
        assert result["key"] == "parent"

    def test_invalid_file_format(self, tmp_path):
        path = tmp_path / "config.txt"
        path.write_text("some text")

        with pytest.raises(ValueError, match="Unsupported config format"):
            load_config(path=path)


class TestConfigOption:
    def test_cli_args_override_config(self, tmp_path):
        runner = CliRunner()
        app = typer.Typer()

        config_path = tmp_path / "config.toml"
        config_path.write_text('output = "from_config"')

        @app.command()
        @config_option(app_name="test")
        def build(output: str = "default"):
            typer.echo(f"output={output}")

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(app, ["--output", "from_cli"])

        assert "output=from_cli" in result.output

    def test_config_file_overrides_default(self, tmp_path):
        runner = CliRunner()
        app = typer.Typer()

        config_path = tmp_path / "config.toml"
        config_path.write_text('output = "from_config"')

        @app.command()
        @config_option(app_name="test")
        def build(output: str = "default"):
            typer.echo(f"output={output}")

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(app, [])

        assert "output=from_config" in result.output

    def test_env_var_overrides_config(self, tmp_path, monkeypatch):
        runner = CliRunner()
        app = typer.Typer()

        config_path = tmp_path / "config.toml"
        config_path.write_text('output = "from_config"')

        monkeypatch.setenv("TEST_OUTPUT", "from_env")

        @app.command()
        @config_option(app_name="test", env_prefix="TEST")
        def build(output: str = "default"):
            typer.echo(f"output={output}")

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(app, [])

        assert "output=from_env" in result.output

    def test_explicit_config_path(self, tmp_path):
        runner = CliRunner()
        app = typer.Typer()

        config_path = tmp_path / "custom.toml"
        config_path.write_text('output = "custom"')

        @app.command()
        @config_option(app_name="test")
        def build(output: str = "default"):
            typer.echo(f"output={output}")

        result = runner.invoke(app, ["--config", str(config_path)])
        assert "output=custom" in result.output

    def test_multiple_parameters(self, tmp_path):
        runner = CliRunner()
        app = typer.Typer()

        config_path = tmp_path / "config.toml"
        config_path.write_text('output = "dist"\nverbose = true\ncount = 5')

        @app.command()
        @config_option(app_name="test")
        def build(output: str = "default", verbose: bool = False, count: int = 1):
            typer.echo(f"{output},{verbose},{count}")

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(app, [])

        assert "dist,True,5" in result.output


class TestConfigMixin:
    def test_get_config(self, tmp_path):
        config_path = tmp_path / "config.toml"
        config_path.write_text('[tool.testapp]\nkey = "value"')

        class TestApp(ConfigMixin, app_name="testapp"):
            pass

        config = TestApp.get_config(path=config_path)
        assert config["key"] == "value"

    def test_subclass_without_app_name(self, tmp_path):
        class TestApp(ConfigMixin):
            pass

        config = TestApp.get_config()
        assert isinstance(config, dict)


class TestEdgeCases:
    def test_config_with_unicode(self, tmp_path):
        config = {"message": "Hello 世界 🌍"}
        path = tmp_path / "config.json"
        path.write_text(json.dumps(config, ensure_ascii=False))

        result = load_config(path=path)
        assert result["message"] == "Hello 世界 🌍"

    def test_nested_config_values(self, tmp_path):
        config = {"database": {"host": "localhost", "port": 5432}}
        path = tmp_path / "config.json"
        path.write_text(json.dumps(config))

        result = load_config(path=path)
        assert result["database"]["host"] == "localhost"

    def test_config_with_lists(self, tmp_path):
        config = {"allowed_envs": ["dev", "staging", "prod"]}
        path = tmp_path / "config.json"
        path.write_text(json.dumps(config))

        result = load_config(path=path)
        assert result["allowed_envs"] == ["dev", "staging", "prod"]

    def test_permission_error_handling(self, tmp_path):
        result = load_config(path="/nonexistent/path/config.json")
        # Should not crash, just return empty or handle gracefully
        assert isinstance(result, dict)

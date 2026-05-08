from __future__ import annotations

import json
import textwrap
import time

import pytest
import typer
from typer.testing import CliRunner

from typer_powertools.extensibility.plugins import PluginManager
from typer_powertools.extensibility.templates import TemplateEngine
from typer_powertools.input.wizard import Step, WizardBuilder
from typer_powertools.lifecycle.cache import CacheManager, cached_command
from typer_powertools.lifecycle.hooks import HookManager
from typer_powertools.migrations.manager import MigrationManager
from typer_powertools.observability.middleware import timing_middleware, use_middleware


class TestHooks:
    def test_before_hook_runs(self):
        runner = CliRunner()
        app = typer.Typer()
        hooks = HookManager()

        called = []

        @hooks.before
        def setup():
            called.append("before")

        @app.command()
        @hooks.wrap
        def cmd():
            called.append("command")

        runner.invoke(app)
        assert called == ["before", "command"]

    def test_after_hook_runs(self):
        runner = CliRunner()
        app = typer.Typer()
        hooks = HookManager()
        called = []

        @hooks.after
        def cleanup():
            called.append("after")

        @app.command()
        @hooks.wrap
        def cmd():
            called.append("command")

        runner.invoke(app)
        assert called == ["command", "after"]

    def test_error_hook_runs_on_exception(self):
        runner = CliRunner()
        app = typer.Typer()
        hooks = HookManager()
        caught_exc = []

        @hooks.error
        def handle_error(exc):
            caught_exc.append(exc)

        @app.command()
        @hooks.wrap
        def cmd():
            raise ValueError("test error")

        runner.invoke(app)
        assert len(caught_exc) == 1
        assert isinstance(caught_exc[0], ValueError)


class TestCache:
    def test_cache_stores_and_retrieves(self, tmp_path):
        cache = CacheManager(app_name="test", cache_dir=tmp_path)
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_cache_expiration(self, tmp_path):
        cache = CacheManager(app_name="test", cache_dir=tmp_path)
        cache.set("key", "value", ttl=1)
        assert cache.get("key") == "value"
        time.sleep(1.1)
        assert cache.get("key") is None

    def test_cache_clear(self, tmp_path):
        cache = CacheManager(app_name="test", cache_dir=tmp_path)
        cache.set("k1", "v1")
        cache.set("k2", "v2")
        cache.clear()
        assert cache.get("k1") is None
        assert cache.get("k2") is None

    def test_cached_command_decorator(self, tmp_path):
        runner = CliRunner()
        app = typer.Typer()

        call_count = [0]

        @app.command()
        @cached_command(ttl=60, app_name="test", cache_dir=tmp_path)
        def expensive(x: int):
            call_count[0] += 1
            return x * 2

        # First call
        runner.invoke(app, ["5"])
        assert call_count[0] == 1

        # Second call (should use cache)
        runner.invoke(app, ["5"])
        assert call_count[0] == 1  # Not incremented


class TestMiddleware:
    def test_middleware_order(self):
        runner = CliRunner()
        app = typer.Typer()
        order = []

        def mw1(next_fn, *args, **kwargs):
            order.append("mw1_before")
            result = next_fn(*args, **kwargs)
            order.append("mw1_after")
            return result

        def mw2(next_fn, *args, **kwargs):
            order.append("mw2_before")
            result = next_fn(*args, **kwargs)
            order.append("mw2_after")
            return result

        @app.command()
        @use_middleware([mw1, mw2])
        def cmd():
            order.append("command")

        runner.invoke(app)
        assert order == ["mw1_before", "mw2_before", "command", "mw2_after", "mw1_after"]

    def test_timing_middleware(self):
        runner = CliRunner()
        app = typer.Typer()

        @app.command()
        @use_middleware([timing_middleware(verbose=False)])
        def cmd():
            time.sleep(0.01)

        result = runner.invoke(app)
        assert result.exit_code == 0


class TestPlugins:
    def test_discover_from_path(self, tmp_path):
        app = typer.Typer()
        plugins = PluginManager(app, plugin_prefix="test_")
        # Create a mock plugin file
        plugin_file = tmp_path / "test_example.py"
        plugin_file.write_text(textwrap.dedent("""\
            import typer

            def register(app):
                @app.command()
                def example():
                    typer.echo("Plugin works!")
        """))
        count = plugins.discover_from_path(tmp_path)
        assert count == 1
        assert "example" in plugins.discovered_plugins

    def test_load_plugin(self, tmp_path):
        app = typer.Typer()
        plugins = PluginManager(app, plugin_prefix="test_")

        plugin_file = tmp_path / "test_example.py"
        plugin_file.write_text(textwrap.dedent("""\
            import typer

            def register(app):
                @app.command(name="plugin_cmd")
                def cmd():
                    typer.echo("Success")
        """))

        plugins.discover_from_path(tmp_path)
        result = plugins.load("example")
        assert result is True
        assert "example" in plugins.loaded_plugins


class TestWizard:
    def test_step_creation(self):
        step = Step("name", "What's your name?", default="Alice")
        assert step.key == "name"
        assert step.prompt == "What's your name?"
        assert step.default == "Alice"

    def test_wizard_builder(self):
        wizard = (
            WizardBuilder("Test").ask("name", "Name?").ask_int("age", "Age?", default=25).build()
        )
        assert len(wizard.steps) == 2
        assert wizard.title == "Test"


class TestTemplates:
    @pytest.fixture(autouse=True)
    def check_jinja(self):
        pytest.importorskip("jinja2")

    def test_render_path(self, tmp_path):
        template_dir = tmp_path / "templates"
        template_dir.mkdir()
        output_dir = tmp_path / "output"

        engine = TemplateEngine(
            template_dir=template_dir, output_dir=output_dir, context={"project_name": "myapp"}
        )

        rendered = engine.render_path("{{project_name}}/main.py")
        assert rendered == "myapp/main.py"

    def test_process_file(self, tmp_path):
        template_dir = tmp_path / "templates"
        template_dir.mkdir()

        # Create a template file
        (template_dir / "config.py.j2").write_text("PROJECT = '{{ name }}'")

        output_dir = tmp_path / "output"
        engine = TemplateEngine(
            template_dir=template_dir, output_dir=output_dir, context={"name": "test"}
        )

        result = engine.process_file(template_dir / "config.py.j2")
        assert result is not None
        assert (output_dir / "config.py").exists()
        assert (output_dir / "config.py").read_text() == "PROJECT = 'test'"


class TestMigrations:
    def test_migration_registration(self):
        manager = MigrationManager(app_name="test")

        @manager.migration("test_mig", from_version="1.0", to_version="2.0")
        def migrate(config):
            config["new"] = "value"
            return config

        assert len(manager.migrations) == 1
        assert manager.migrations[0].name == "test_mig"

    def test_get_current_version(self):
        manager = MigrationManager(version_key="_v")
        config = {"_v": "1.0"}
        assert manager.get_current_version(config) == "1.0"

    def test_migrate(self):
        manager = MigrationManager()

        @manager.migration("v1_to_v2", from_version="1.0", to_version="2.0")
        def mig1(config):
            config["field2"] = config.pop("field1")
            return config

        @manager.migration("v2_to_v3", from_version="2.0", to_version="3.0")
        def mig2(config):
            config["field3"] = "new"
            return config

        config = {"_version": "1.0", "field1": "value"}
        migrated = manager.migrate(config, to_version="3.0")

        assert migrated["_version"] == "3.0"
        assert "field1" not in migrated
        assert migrated["field2"] == "value"
        assert migrated["field3"] == "new"

    def test_load_and_migrate(self, tmp_path):
        manager = MigrationManager()

        @manager.migration("v1_to_v2", from_version="1.0", to_version="2.0")
        def migrate(config):
            config["updated"] = True
            return config

        config_file = tmp_path / "config.json"
        config_file.write_text(json.dumps({"_version": "1.0", "data": "test"}))

        result = manager.load_and_migrate(config_file, backup=False)
        assert result["_version"] == "2.0"
        assert result["updated"] is True

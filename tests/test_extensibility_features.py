import pytest
import typer
from typer.testing import CliRunner

from typer_powertools.core.app import PowertyperApp
from typer_powertools.extensibility.plugins import PluginManager
from typer_powertools.migrations.manager import MigrationManager

runner = CliRunner()


def test_entry_point_function_name():
    import sys
    import types

    fake_mod = types.ModuleType("my_fake_plugin")
    fake_mod.__version__ = "1.0"  # type: ignore

    def my_plugin_func(app):
        return "registered"

    fake_mod.my_func = my_plugin_func  # type: ignore
    sys.modules["my_fake_plugin"] = fake_mod

    pm = PluginManager(typer.Typer())
    proxy = pm._load_from_entry_point("my_fake_plugin:my_func")
    assert proxy.register(None) == "registered"
    assert proxy.__version__ == "1.0"

    del sys.modules["my_fake_plugin"]


def test_bug7_toml_yaml_migrations(tmp_path):
    toml_path = tmp_path / "config.toml"
    with open(toml_path, "w") as f:
        f.write('version = "1"\nkey = "old"')

    manager = MigrationManager(version_key="version")

    @manager.migration("v1_to_v2", from_version="1", to_version="2")
    def mig(c):
        c["key"] = "new"
        return c

    try:
        import tomllib
    except ImportError:
        try:
            import tomli
        except ImportError:
            pytest.skip("No toml parser")

    try:
        import tomli_w
    except ImportError:
        try:
            import toml
        except ImportError:
            pytest.skip("No toml writer")

    res = manager.load_and_migrate(toml_path, to_version="2", backup=False)
    assert res["version"] == "2"
    assert res["key"] == "new"


def test_feature_powertyper_app():
    app = PowertyperApp("mycli").with_shell().with_hooks().build()
    cmds = [c.name for c in app.registered_commands]
    assert "shell" in cmds


def test_feature_powertyper_app_with_audit(tmp_path):
    db_path = tmp_path / "audit.db"
    app = PowertyperApp("mycli").with_audit(db_path=str(db_path)).build()
    group_names = [g.typer_instance.info.name for g in app.registered_groups]
    assert "audit" in group_names

    # Invoke audit history to ensure the subgroup works
    res = runner.invoke(app, ["audit", "history", "--limit", "0"])
    assert res.exit_code == 0


def test_feature_powertyper_app_shell_command_registered():
    app = PowertyperApp("myshell").with_shell().build()
    res = runner.invoke(app, ["shell", "--help"])
    assert res.exit_code == 0
    assert "shell" in res.stdout.lower()

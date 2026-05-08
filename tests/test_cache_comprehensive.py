import time

import pytest
import typer
from typer.testing import CliRunner

from typer_powertools.lifecycle.cache import (
    CacheManager,
    cached_command,
    register_cache_commands,
    temporary_cache,
)


class TestCacheManager:
    def test_basic_set_and_get(self, tmp_path):
        cache = CacheManager(app_name="test", cache_dir=tmp_path)
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_get_nonexistent_key(self, tmp_path):
        cache = CacheManager(app_name="test", cache_dir=tmp_path)
        assert cache.get("nonexistent") is None

    def test_get_with_default(self, tmp_path):
        cache = CacheManager(app_name="test", cache_dir=tmp_path)
        assert cache.get("missing", default="fallback") == "fallback"

    def test_ttl_expiration(self, tmp_path):
        cache = CacheManager(app_name="test", cache_dir=tmp_path)
        cache.set("key", "value", ttl=1)
        assert cache.get("key") == "value"
        time.sleep(1.1)
        assert cache.get("key") is None

    def test_no_ttl_persists(self, tmp_path):
        cache = CacheManager(app_name="test", cache_dir=tmp_path)
        cache.set("key", "value", ttl=None)
        time.sleep(0.5)
        assert cache.get("key") == "value"

    def test_delete_key(self, tmp_path):
        cache = CacheManager(app_name="test", cache_dir=tmp_path)
        cache.set("key", "value")
        assert cache.get("key") == "value"
        cache.delete("key")
        assert cache.get("key") is None

    def test_delete_nonexistent_key(self, tmp_path):
        cache = CacheManager(app_name="test", cache_dir=tmp_path)
        cache.delete("nonexistent")  # Should not raise

    def test_clear_all(self, tmp_path):
        cache = CacheManager(app_name="test", cache_dir=tmp_path)
        cache.set("k1", "v1")
        cache.set("k2", "v2")
        cache.set("k3", "v3")
        cache.clear()
        assert cache.get("k1") is None
        assert cache.get("k2") is None
        assert cache.get("k3") is None

    def test_clear_expired(self, tmp_path):
        cache = CacheManager(app_name="test", cache_dir=tmp_path)
        cache.set("expired", "value", ttl=1)
        cache.set("valid", "value", ttl=10)
        time.sleep(1.1)
        count = cache.clear_expired()
        assert count == 1
        assert cache.get("expired") is None
        assert cache.get("valid") == "value"

    def test_stats(self, tmp_path):
        cache = CacheManager(app_name="test", cache_dir=tmp_path)
        cache.set("k1", "v1")
        cache.set("k2", "v2", ttl=1)
        time.sleep(1.1)

        stats = cache.stats()
        assert stats["total_entries"] == 2
        assert stats["expired_entries"] == 1
        assert stats["active_entries"] == 1
        assert stats["total_size_bytes"] > 0

    def test_different_data_types(self, tmp_path):
        cache = CacheManager(app_name="test", cache_dir=tmp_path)
        cache.set("str", "value")
        assert cache.get("str") == "value"

        cache.set("int", 42)
        assert cache.get("int") == 42

        cache.set("float", 3.14)
        assert cache.get("float") == pytest.approx(3.14)

        cache.set("list", [1, 2, 3])
        assert cache.get("list") == [1, 2, 3]

        cache.set("dict", {"key": "value"})
        assert cache.get("dict") == {"key": "value"}

        # None (should work)
        cache.set("none", None)
        assert cache.get("none") is None

    def test_key_collision(self, tmp_path):
        cache = CacheManager(app_name="test", cache_dir=tmp_path)
        cache.set("key", "first")
        cache.set("key", "second")  # Overwrite
        assert cache.get("key") == "second"

    def test_unicode_keys(self, tmp_path):
        cache = CacheManager(app_name="test", cache_dir=tmp_path)
        cache.set("キー", "日本語")
        assert cache.get("キー") == "日本語"

    def test_large_values(self, tmp_path):
        cache = CacheManager(app_name="test", cache_dir=tmp_path)
        large_value = "x" * 10000
        cache.set("large", large_value)
        assert cache.get("large") == large_value

    def test_corrupted_cache_file(self, tmp_path):
        cache = CacheManager(app_name="test", cache_dir=tmp_path)
        cache.set("key", "value")

        # Corrupt the cache file
        cache_file = list(tmp_path.glob("*.cache"))[0]
        cache_file.write_bytes(b"corrupted data")

        # Should return default gracefully
        assert cache.get("key", default="fallback") == "fallback"

    def test_empty_cache_dir(self, tmp_path):
        cache = CacheManager(app_name="test", cache_dir=tmp_path)
        stats = cache.stats()
        assert stats["total_entries"] == 0


class TestCachedCommand:
    def test_caches_result(self, tmp_path):
        runner = CliRunner()
        app = typer.Typer()

        call_count = [0]

        @app.command()
        @cached_command(ttl=60, app_name="test", cache_dir=tmp_path)
        def expensive(x: int):
            call_count[0] += 1
            typer.echo(f"result={x * 2}")
            return True

        result1 = runner.invoke(app, ["5"])
        assert call_count[0] == 1
        assert "result=10" in result1.output

        result2 = runner.invoke(app, ["5"])
        assert call_count[0] == 1  # Still 1, not called again
        assert "cache hit" in result2.output.lower()

    def test_different_args_not_cached(self, tmp_path):
        runner = CliRunner()
        app = typer.Typer()
        call_count = [0]

        @app.command()
        @cached_command(ttl=60, app_name="test", cache_dir=tmp_path)
        def cmd(x: int):
            call_count[0] += 1
            typer.echo(f"x={x}")
            return True

        runner.invoke(app, ["1"])
        runner.invoke(app, ["2"])

        assert call_count[0] == 2  # Different args, both called

    def test_cache_expiration(self, tmp_path):
        runner = CliRunner()
        app = typer.Typer()

        call_count = [0]

        @app.command()
        @cached_command(ttl=1, app_name="test", cache_dir=tmp_path)
        def cmd(x: int):
            call_count[0] += 1
            typer.echo(f"x={x}")
            return True

        runner.invoke(app, ["5"])
        assert call_count[0] == 1

        time.sleep(1.1)
        runner.invoke(app, ["5"])
        assert call_count[0] == 2  # Cache expired, called again

    def test_no_ttl_caches_forever(self, tmp_path):
        runner = CliRunner()
        app = typer.Typer()

        call_count = [0]

        @app.command()
        @cached_command(ttl=None, app_name="test", cache_dir=tmp_path)
        def cmd(x: int):
            call_count[0] += 1
            typer.echo(f"x={x}")
            return True

        runner.invoke(app, ["5"])
        time.sleep(0.5)
        runner.invoke(app, ["5"])

        assert call_count[0] == 1  # Still cached

    def test_include_args_false(self, tmp_path):
        runner = CliRunner()
        app = typer.Typer()

        call_count = [0]

        @app.command()
        @cached_command(ttl=60, app_name="test", cache_dir=tmp_path, include_args=False)
        def cmd(x: int):
            call_count[0] += 1
            typer.echo(f"x={x}")
            return True

        runner.invoke(app, ["1"])
        runner.invoke(app, ["2"])  # Different arg, but not included in key

        assert call_count[0] == 1  # Cached regardless of args

    def test_custom_key_func(self, tmp_path):
        runner = CliRunner()
        app = typer.Typer()

        call_count = [0]

        def custom_key(x: int):
            return f"custom-{x % 2}"  # Even/odd grouping

        @app.command()
        @cached_command(ttl=60, app_name="test", cache_dir=tmp_path, key_func=custom_key)
        def cmd(x: int):
            call_count[0] += 1
            typer.echo(f"x={x}")
            return True

        runner.invoke(app, ["2"])
        runner.invoke(app, ["4"])  # Same key (both even)

        assert call_count[0] == 1


class TestRegisterCacheCommands:
    def test_stats_command(self, tmp_path):
        runner = CliRunner()
        app = typer.Typer()

        cache = CacheManager(app_name="test", cache_dir=tmp_path)
        cache.set("k1", "v1")
        cache.set("k2", "v2")

        register_cache_commands(app, app_name="test", cache_dir=tmp_path)

        result = runner.invoke(app, ["cache", "stats"])
        assert result.exit_code == 0
        assert "2" in result.output  # 2 entries

    def test_clear_command_with_yes_flag(self, tmp_path):
        runner = CliRunner()
        app = typer.Typer()

        cache = CacheManager(app_name="test", cache_dir=tmp_path)
        cache.set("k1", "v1")

        register_cache_commands(app, app_name="test", cache_dir=tmp_path)

        result = runner.invoke(app, ["cache", "clear", "--yes"])
        assert result.exit_code == 0
        assert cache.get("k1") is None

    def test_clear_expired_only(self, tmp_path):
        runner = CliRunner()
        app = typer.Typer()

        cache = CacheManager(app_name="test", cache_dir=tmp_path)
        cache.set("expired", "v1", ttl=1)
        cache.set("valid", "v2", ttl=10)
        time.sleep(1.1)

        register_cache_commands(app, app_name="test", cache_dir=tmp_path)

        result = runner.invoke(app, ["cache", "clear", "--expired-only"])
        assert result.exit_code == 0
        assert cache.get("expired") is None
        assert cache.get("valid") == "v2"

    def test_info_command(self, tmp_path):
        runner = CliRunner()
        app = typer.Typer()

        register_cache_commands(app, app_name="test", cache_dir=tmp_path)

        result = runner.invoke(app, ["cache", "info"])
        assert result.exit_code == 0
        assert "test" in result.output


class TestTemporaryCache:
    def test_clears_on_exit(self, tmp_path):
        with temporary_cache(ttl=60, app_name="test") as cache:
            cache.cache_dir = tmp_path
            cache.set("key", "value")
            assert cache.get("key") == "value"

        # After exit, cache should be cleared
        cache2 = CacheManager(app_name="test", cache_dir=tmp_path)
        assert cache2.get("key") is None

    def test_exception_still_clears(self, tmp_path):
        try:
            with temporary_cache(ttl=60, app_name="test") as cache:
                cache.cache_dir = tmp_path
                cache.set("key", "value")
                raise ValueError("test")
        except ValueError:
            pass

        cache2 = CacheManager(app_name="test", cache_dir=tmp_path)
        assert cache2.get("key") is None


class TestEdgeCases:
    def test_cache_with_None_value(self, tmp_path):
        cache = CacheManager(app_name="test", cache_dir=tmp_path)
        cache.set("key", None)
        # Getting None is ambiguous with "not found"
        assert cache.get("key") is None

    def test_very_long_key(self, tmp_path):
        cache = CacheManager(app_name="test", cache_dir=tmp_path)
        long_key = "k" * 1000
        cache.set(long_key, "value")
        assert cache.get(long_key) == "value"

    def test_special_chars_in_key(self, tmp_path):
        cache = CacheManager(app_name="test", cache_dir=tmp_path)
        special_key = "key/with\\special:chars"
        cache.set(special_key, "value")
        assert cache.get(special_key) == "value"

    def test_concurrent_access(self, tmp_path):
        # Simplified test - real concurrent test would need threading
        cache1 = CacheManager(app_name="test", cache_dir=tmp_path)
        cache2 = CacheManager(app_name="test", cache_dir=tmp_path)

        cache1.set("key", "value1")
        cache2.set("key", "value2")

        assert cache1.get("key") == "value2"

    def test_zero_ttl(self, tmp_path):
        cache = CacheManager(app_name="test", cache_dir=tmp_path)
        cache.set("key", "value", ttl=0)
        # Should expire immediately
        assert cache.get("key") is None

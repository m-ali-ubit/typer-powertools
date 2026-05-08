import asyncio
import json

import pytest

from typer_powertools.lifecycle.cache import CacheManager, cached_command_async
from typer_powertools.lifecycle.hooks import on_before, reset_default_manager


def test_hooks_singletons():
    reset_default_manager()
    flag = []

    @on_before
    def dummy_hook():
        flag.append(1)

    import typer_powertools.lifecycle.hooks as hooks

    assert len(hooks._default_manager._before_hooks) == 1
    reset_default_manager()
    assert len(hooks._default_manager._before_hooks) == 0


def test_cache_json_serializer(tmp_path):
    cache = CacheManager(app_name="testapp", cache_dir=tmp_path, serializer="json")
    cache.set("mykey", {"hello": "world"}, ttl=60)

    files = list(tmp_path.glob("*.cache"))
    assert len(files) == 1
    with open(files[0], "r") as f:
        raw = json.load(f)
        assert raw["value"] == {"hello": "world"}
        assert "expires_at" in raw

    val = cache.get("mykey")
    assert val == {"hello": "world"}


@pytest.mark.asyncio
async def test_feature_async_cache(tmp_path):
    cache_dir = tmp_path / "async_cache"

    @cached_command_async(app_name="testapp", cache_dir=cache_dir)
    async def fetch_data():
        await asyncio.sleep(0.01)
        return {"status": "ok"}

    r1 = await fetch_data()
    r2 = await fetch_data()
    assert r1 == {"status": "ok"}
    assert r1 == r2

import asyncio

import pytest

from typer_powertools.observability.audit import audit_command_async
from typer_powertools.observability.middleware import (
    register_global_middleware,
    reset_global_registry,
)


def test_middleware_singletons():
    reset_global_registry()
    register_global_middleware(lambda n: n)
    import typer_powertools.observability.middleware as mw

    assert len(mw._global_registry.middlewares) == 1

    reset_global_registry()
    assert len(mw._global_registry.middlewares) == 0


@pytest.mark.asyncio
async def test_feature_async_audit(tmp_path):
    db_path = tmp_path / "async_audit.db"

    @audit_command_async(app_name="testapp", db_path=db_path)
    async def perform_task():
        await asyncio.sleep(0.01)
        return True

    await perform_task()

    assert db_path.exists()

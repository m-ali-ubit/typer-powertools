"""
Command output caching with TTL for expensive operations.

Cache command results to disk with configurable expiration times.

Usage
-----
    from typer_powertools.lifecycle.cache import cached_command, CacheManager
    import typer

    app = typer.Typer()

    @app.command()
    @cached_command(ttl=3600)  # cache for 1 hour
    def fetch_data(source: str) -> dict:
        # Expensive API call
        return call_api(source)

    # Manual cache management:
    cache = CacheManager(app_name="myapp")
    cache.set("key", "value", ttl=300)
    value = cache.get("key")
    cache.clear()
    cache.clear_expired()
"""

from __future__ import annotations

import functools
import hashlib
import inspect
import json
import os
import pickle
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, TypeVar

import typer
from rich.console import Console

console = Console()
F = TypeVar("F", bound=Callable[..., Any])

_MISSING = object()


class CacheManager:
    def __init__(
        self,
        app_name: str = "app",
        cache_dir: Optional[Path] = None,
        serializer: str = "json",
    ) -> None:
        """
        Parameters
        ----------
        app_name:
            Application name used to determine default cache directory.
        cache_dir:
            Explicit cache directory. If *None*, uses platform default.
        serializer:
            Serialization format: "json" or "pickle".
        """
        self.serializer = serializer
        if cache_dir is not None:
            self.cache_dir = Path(cache_dir)
        else:
            self.cache_dir = self._default_cache_dir(app_name)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _default_cache_dir(self, app_name: str) -> Path:
        """Platform-specific cache directory."""
        if sys.platform == "win32":
            base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        elif sys.platform == "darwin":
            base = Path.home() / "Library" / "Caches"
        else:
            base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        return base / app_name

    def _key_to_path(self, key: str) -> Path:
        """Convert a cache key to a SHA-256-based file path inside ``cache_dir``."""
        safe_key = hashlib.sha256(key.encode()).hexdigest()
        return self.cache_dir / f"{safe_key}.cache"

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a cached value by key.

        Returns *default* if the key is missing or the entry has expired.
        Expired entries are automatically deleted from disk.
        """
        path = self._key_to_path(key)
        if not path.exists():
            return default

        try:
            with open(path, "rb") as f:
                if self.serializer == "json":
                    data = json.loads(f.read().decode())
                else:
                    data = pickle.load(f)
            if (
                "expires_at" in data
                and data["expires_at"] is not None
                and data["expires_at"] < time.time()
            ):
                path.unlink()
                return default

            return data["value"]
        except Exception as exc:
            console.print(f"[dim yellow]⚠ cache read error: {exc}[/dim yellow]")
            return default

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Store a value in the cache.

        Parameters
        ----------
        key: Cache key string.
        value: JSON-serializable (or picklable) value to store.
        ttl: Time-to-live in seconds. *None* means the entry never expires.
        """
        path = self._key_to_path(key)
        data = {
            "value": value,
            "created_at": time.time(),
            "expires_at": time.time() + ttl if ttl is not None else None,
        }

        try:
            with open(path, "wb") as f:
                if self.serializer == "json":
                    f.write(json.dumps(data, default=str).encode())
                else:
                    pickle.dump(data, f)
        except Exception as exc:
            console.print(f"[dim yellow]⚠ cache write error: {exc}[/dim yellow]")

    def delete(self, key: str) -> None:
        """Remove a single cache entry by key. No-ops if the key doesn't exist."""
        path = self._key_to_path(key)
        if path.exists():
            path.unlink()

    def clear(self) -> None:
        """Delete all cache entries regardless of expiration."""
        for cache_file in self.cache_dir.glob("*.cache"):
            cache_file.unlink()

    def clear_expired(self) -> int:
        """Delete all cache entries that have passed their TTL.

        Returns
        -------
        int
            Number of expired entries removed.
        """
        removed = 0
        now = time.time()
        for cache_file in self.cache_dir.glob("*.cache"):
            try:
                with open(cache_file, "rb") as f:
                    if self.serializer == "json":
                        data = json.loads(f.read().decode())
                    else:
                        data = pickle.load(f)
                if (
                    "expires_at" in data
                    and data["expires_at"] is not None
                    and data["expires_at"] < now
                ):
                    cache_file.unlink()
                    removed += 1
            except Exception:
                pass
        return removed

    def stats(self) -> Dict[str, Any]:
        """Return a summary of cache usage.

        Returns
        -------
        dict
            Keys: ``total_entries``, ``expired_entries``, ``active_entries``,
            ``total_size_bytes``, ``cache_dir``.
        """
        total = 0
        expired = 0
        total_size = 0
        now = time.time()

        for cache_file in self.cache_dir.glob("*.cache"):
            total += 1
            total_size += cache_file.stat().st_size
            try:
                with open(cache_file, "rb") as f:
                    if self.serializer == "json":
                        data = json.loads(f.read().decode())
                    else:
                        data = pickle.load(f)
                if (
                    "expires_at" in data
                    and data["expires_at"] is not None
                    and data["expires_at"] < now
                ):
                    expired += 1
            except Exception:
                pass

        return {
            "total_entries": total,
            "expired_entries": expired,
            "active_entries": total - expired,
            "total_size_bytes": total_size,
            "cache_dir": str(self.cache_dir),
        }


def cached_command(
    ttl: Optional[int] = None,
    key_func: Optional[Callable[..., str]] = None,
    app_name: str = "app",
    cache_dir: Optional[Path] = None,
    include_args: bool = True,
) -> Callable[[F], F]:
    """Decorator that caches command results.

    Parameters
    ----------
    ttl:
        Time-to-live in seconds. *None* = cache forever.
    key_func:
        Custom function to generate cache key from args/kwargs.
        If *None*, uses command name + serialized args.
    app_name:
        Application name for cache directory.
    cache_dir:
        Explicit cache directory path.
    include_args:
        Whether to include function arguments in cache key.

    Example
    -------
    ::
        @app.command()
        @cached_command(ttl=3600, app_name="myapp")
        def fetch(source: str) -> dict:
            return expensive_api_call(source)
    """
    cache = CacheManager(app_name=app_name, cache_dir=cache_dir)

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                cmd_name = func.__name__
                if include_args:
                    sig = inspect.signature(func)
                    bound = sig.bind(*args, **kwargs)
                    bound.apply_defaults()
                    args_str = json.dumps(bound.arguments, sort_keys=True, default=str)
                    cache_key = f"{cmd_name}:{args_str}"
                else:
                    cache_key = cmd_name

            cached_value = cache.get(cache_key, default=_MISSING)
            if cached_value is not _MISSING:
                console.print("[dim]✓ cache hit[/dim]")
                return cached_value

            console.print("[dim]⊗ cache miss — executing…[/dim]")
            result = func(*args, **kwargs)

            cache.set(cache_key, result, ttl=ttl)
            return result

        wrapper.__signature__ = inspect.signature(func)  # type: ignore
        return wrapper  # type: ignore[return-value]

    return decorator


def cached_command_async(
    ttl: Optional[int] = None,
    key_func: Optional[Callable[..., str]] = None,
    app_name: str = "app",
    cache_dir: Optional[Path] = None,
    include_args: bool = True,
) -> Callable[[F], F]:
    """Async version of :func:`cached_command` for ``async def`` Typer commands.

    Identical parameters to :func:`cached_command`; the wrapper is a coroutine
    so it can be used with ``await``.
    """
    cache = CacheManager(app_name=app_name, cache_dir=cache_dir)

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                cmd_name = func.__name__
                if include_args:
                    sig = inspect.signature(func)
                    bound = sig.bind(*args, **kwargs)
                    bound.apply_defaults()
                    args_str = json.dumps(bound.arguments, sort_keys=True, default=str)
                    cache_key = f"{cmd_name}:{args_str}"
                else:
                    cache_key = cmd_name

            cached_value = cache.get(cache_key, default=_MISSING)
            if cached_value is not _MISSING:
                console.print("[dim]✓ cache hit[/dim]")
                return cached_value

            console.print("[dim]⊗ cache miss — executing…[/dim]")
            result = await func(*args, **kwargs)

            cache.set(cache_key, result, ttl=ttl)
            return result

        wrapper.__signature__ = inspect.signature(func)  # type: ignore
        return wrapper  # type: ignore[return-value]

    return decorator


def register_cache_commands(
    app: typer.Typer,
    app_name: str = "app",
    cache_dir: Optional[Path] = None,
    command_group_name: str = "cache",
) -> None:
    """Register cache management sub-commands.

    Adds:
        <cli> cache stats
        <cli> cache clear [--expired-only]
        <cli> cache info

    Parameters
    ----------
    app:
        Parent Typer app.
    app_name:
        Application name.
    cache_dir:
        Explicit cache directory.
    command_group_name:
        Name of the sub-command group.
    """
    cache = CacheManager(app_name=app_name, cache_dir=cache_dir)
    cache_app = typer.Typer(name=command_group_name, help="Cache management.")
    app.add_typer(cache_app)

    @cache_app.command("stats")
    def stats() -> None:
        s = cache.stats()
        console.print("\n[bold]Cache Statistics[/bold]")
        console.print(f"  Total entries:   [cyan]{s['total_entries']}[/cyan]")
        console.print(f"  Active entries:  [green]{s['active_entries']}[/green]")
        console.print(f"  Expired entries: [yellow]{s['expired_entries']}[/yellow]")
        console.print(f"  Total size:      [cyan]{s['total_size_bytes']:,} bytes[/cyan]")
        console.print(f"  Cache dir:       [dim]{s['cache_dir']}[/dim]\n")

    @cache_app.command("clear")
    def clear(
        expired_only: bool = typer.Option(
            False, "--expired-only", help="Only remove expired entries."
        ),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
    ) -> None:
        if expired_only:
            count = cache.clear_expired()
            console.print(f"[green]✓ Removed {count} expired entries.[/green]")
        else:
            if not yes:
                confirmed = typer.confirm("Clear all cache entries?")
                if not confirmed:
                    raise typer.Abort()
            cache.clear()
            console.print("[green]✓ Cache cleared.[/green]")

    @cache_app.command("info")
    def info() -> None:
        console.print(f"\n[bold]Cache Configuration[/bold]")
        console.print(f"  App name:   [cyan]{app_name}[/cyan]")
        console.print(f"  Directory:  [cyan]{cache.cache_dir}[/cyan]")
        console.print(f"  Serializer: [cyan]{cache.serializer}[/cyan]\n")


from contextlib import contextmanager
from typing import Generator


@contextmanager
def temporary_cache(ttl: int = 300, app_name: str = "temp") -> Generator[CacheManager, None, None]:
    """Context manager that provides a temporary cache, cleared on exit.
    Example
    -------
    ::
        with temporary_cache(ttl=60) as cache:
            cache.set("key", "value")
            # ... use cache ...
        # cache is cleared automatically
    """
    cache = CacheManager(app_name=app_name)
    try:
        yield cache
    finally:
        cache.clear()

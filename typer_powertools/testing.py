from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Mapping, Optional, Sequence

import typer
from typer.testing import CliRunner, Result

runner = CliRunner()


def run_cli(
    app: typer.Typer,
    args: Sequence[str] | None = None,
    env: Optional[Mapping[str, str]] = None,
) -> Result:
    """Invoke a Typer app with sensible defaults for tests.

    Parameters
    ----------
    app:
        The :class:`typer.Typer` application to invoke.
    args:
        CLI arguments as a sequence of strings.
    env:
        Optional environment variables to inject for this invocation.

    Returns
    -------
    Result
        The Click ``Result`` object containing ``exit_code``, ``output``,
        and ``exception``.

    Example
    -------
    ::
        result = run_cli(app, ["deploy", "--env", "staging"])
        assert result.exit_code == 0
        assert "Deployed" in result.output
    """
    return runner.invoke(app, list(args or []), env=dict(env or {}))


@contextmanager
def temp_config_file(
    data: Dict[str, Any],
    suffix: str = ".json",
    *,
    directory: Optional[Path] = None,
) -> Iterator[Path]:
    """Create a temporary config file for the duration of a test.

    Each call creates a **uniquely named** file, so parallel tests do not
    interfere with each other.  The file is automatically deleted when the
    context manager exits, even if the test raises an exception.

    Parameters
    ----------
    data:
        Dictionary to serialize as JSON (written via :func:`json.dumps`).
    suffix:
        File suffix (default: ``.json``). Use ``".toml"`` or ``".yaml"`` to
        test other config formats, but note that only JSON is written by this
        helper — you may need to write the file yourself for other formats.
    directory:
        Optional directory in which to create the file. If omitted, the
        system temporary directory is used.

    Yields
    ------
    Path
        Absolute path to the temporary config file.

    Example
    -------
    ::

        with temp_config_file({"output": "dist", "verbose": True}) as cfg:
            result = run_cli(app, ["build", "--config", str(cfg)])
        assert result.exit_code == 0
    """
    base_dir = Path(directory) if directory else Path(tempfile.gettempdir())
    base_dir.mkdir(parents=True, exist_ok=True)

    fd, raw_path = tempfile.mkstemp(suffix=suffix, dir=base_dir, prefix="typer_pt_test_")
    path = Path(raw_path)
    try:
        os.close(fd)
        path.write_text(json.dumps(data), encoding="utf-8")
        yield path
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass

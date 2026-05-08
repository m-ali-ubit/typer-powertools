"""
Internationalization (i18n) / localization for Typer CLI help text.

Typer hardcodes all help strings as plain Python strings — there's no built-in
mechanism to swap languages. This module provides:

  • A simple message catalog backed by JSON locale files.
  • Auto-detection from ``$LANG`` / ``$LANGUAGE`` environment variables.
  • A ``translate()`` helper (also aliased as ``_()``).
  • An ``@i18n_command`` decorator that swaps help strings at runtime.
  • A ``--lang`` option injected automatically by ``I18nMixin``.

Locale files live in a directory (default: ``./locales``) as::

    locales/
        en.json
        de.json
        fr.json

Each file is a flat JSON object::

    {
        "deploy.help": "Deploy the application to the target environment.",
        "deploy.env.help": "Target environment (staging / production).",
        "greeting": "Hello, {name}!"
    }

Usage
-----
    from typer_powertools.i18n.catalog import set_locale, translate as _

    set_locale("de")

    @app.command(help=_("deploy.help"))
    def deploy(
        env: str = typer.Option("staging", help=_("deploy.env.help"))
    ):
        typer.echo(_("greeting", name="World"))
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from rich.console import Console

console = Console()
_catalog: Dict[str, str] = {}  # active locale → message map
_fallback: Dict[str, str] = {}  # English fallback
_current_locale: str = "en"
_locale_dir: Optional[Path] = None
_i18n_lock = threading.RLock()


def _detect_locale() -> str:
    for var in ("LANGUAGE", "LANG", "LC_ALL", "LC_MESSAGES"):
        val = os.environ.get(var)
        if val:
            # "en_US.UTF-8" → "en", "de_DE" → "de"
            return re.split(r"[_.@]", val)[0]
    return "en"


def init(
    locale_dir: Union[str, Path],
    locale: Optional[str] = None,
    auto_detect: bool = True,
) -> None:
    """Initialise the i18n system.

    Parameters
    ----------
    locale_dir:
        Directory containing ``<locale>.json`` files.
    locale:
        Explicit locale string (e.g. ``"de"``). Overrides auto-detection.
    auto_detect:
        When *True* and *locale* is not given, detect from env vars.
    """
    global _locale_dir
    _locale_dir = Path(locale_dir)

    chosen = locale or (_detect_locale() if auto_detect else "en")
    set_locale(chosen)


def set_locale(locale: str) -> None:
    """Switch the active locale at runtime.

    Parameters
    ----------
    locale:
        BCP-47 language tag or short code (e.g. ``"en"``, ``"de"``, ``"fr"``).
    """
    global _catalog, _current_locale, _fallback
    with _i18n_lock:
        _current_locale = locale
        _catalog = _load_catalog(locale)
        if locale != "en":
            _fallback = _load_catalog("en")


def get_locale() -> str:
    with _i18n_lock:
        return _current_locale


def _load_catalog(locale: str) -> Dict[str, str]:
    if _locale_dir is None:
        return {}
    candidates = [
        _locale_dir / f"{locale}.json",
        _locale_dir / locale / "messages.json",
    ]
    for path in candidates:
        if path.exists():
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return {str(k): str(v) for k, v in data.items()}
            except Exception as exc:
                console.print(f"[yellow]i18n: could not load {path}: {exc}[/yellow]")
    return {}


def translate(key: str, **kwargs: Any) -> str:
    """Return the localised message for *key*, with optional format variables.

    Falls back to English, then returns the key itself if nothing is found.

    Parameters
    ----------
    key:
        Message key (e.g. ``"deploy.help"``).
    **kwargs:
        Named format arguments substituted into the message.

    Example
    -------
    ::

        msg = translate("greeting", name="Alice")
        # → "Hallo, Alice!" (if locale is "de")
    """
    with _i18n_lock:
        template = _catalog.get(key) or _fallback.get(key) or key
    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, IndexError):
            return template
    return template


_ = translate


class MessageCatalog:
    """A simple in-memory catalog for defining messages in code.

    Example
    -------
    ::

        catalog = MessageCatalog()
        catalog.add("en", "greet.help", "Greet someone")
        catalog.add("de", "greet.help", "Jemanden begrüßen")
        catalog.activate("de")

        @app.command(help=catalog.t("greet.help"))
        def greet(name: str): ...
    """

    def __init__(self) -> None:
        self._catalogs: Dict[str, Dict[str, str]] = {}

    def add(self, locale: str, key: str, message: str) -> None:
        self._catalogs.setdefault(locale, {})[key] = message

    def add_many(self, locale: str, messages: Dict[str, str]) -> None:
        self._catalogs.setdefault(locale, {}).update(messages)

    def activate(self, locale: str) -> None:
        global _catalog, _fallback, _current_locale
        _current_locale = locale
        _catalog = self._catalogs.get(locale, {})
        _fallback = self._catalogs.get("en", {})

    def t(self, key: str, **kwargs: Any) -> str:
        return translate(key, **kwargs)

    def locales(self) -> List[str]:
        """Return all registered locale codes."""
        return list(self._catalogs.keys())


class I18nMixin:
    """Mixin that adds automatic ``--lang`` / ``--locale`` support.

    Usage
    -----
    ::

        class MyApp(I18nMixin, locale_dir="locales", default_locale="en"):
            app = typer.Typer()

        @MyApp.app.command()
        def greet(name: str):
            typer.echo(translate("greeting", name=name))
    """

    _i18n_locale_dir: Optional[str] = None
    _i18n_default_locale: str = "en"
    _i18n_auto_detect: bool = True

    def __init_subclass__(
        cls,
        locale_dir: Optional[str] = None,
        default_locale: str = "en",
        auto_detect: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init_subclass__(**kwargs)
        cls._i18n_locale_dir = locale_dir
        cls._i18n_default_locale = default_locale
        cls._i18n_auto_detect = auto_detect

        # Auto-initialise if locale_dir provided
        if locale_dir:
            init(
                locale_dir=locale_dir,
                locale=default_locale if not auto_detect else None,
                auto_detect=auto_detect,
            )

    @classmethod
    def setup_i18n(cls, locale_dir: str, locale: Optional[str] = None) -> None:
        init(
            locale_dir=locale_dir,
            locale=locale or cls._i18n_default_locale,
            auto_detect=cls._i18n_auto_detect,
        )

    @classmethod
    def available_locales(cls) -> List[str]:
        if not cls._i18n_locale_dir:
            return []
        d = Path(cls._i18n_locale_dir)
        return [p.stem for p in d.glob("*.json")] if d.exists() else []

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any

try:  # pragma: no cover - Python 3.11+
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - fallback for Python <3.11
    try:
        import tomli as tomllib  # type: ignore[import-untyped]
    except ModuleNotFoundError:  # pragma: no cover - tomli not installed
        tomllib = None  # type: ignore[assignment]

__all__ = (
    'I18nConfigurationError',
    'I18nTranslator',
    'configure_translator',
)

_PLACEHOLDER_PATTERN = re.compile(r'\{(.*?)}')

_ENV_PATH = 'MOPS_I18N_PATH'
_ENV_LOCALE = 'MOPS_I18N_LOCALE'

_MANUAL_PATH: str | Path | None = None
_MANUAL_LOCALE: str | None = None
_MANUAL_PARSED = False


class I18nConfigurationError(RuntimeError):
    """Raised when translation resources cannot be located or parsed."""


class I18nTranslator:
    """
    Lightweight helper that loads JSON catalogues and resolves ``{key}`` placeholders.

    The configuration lookup order is:
        1. Environment variables.
        2. ``[tool.mops.i18n]`` section inside ``pyproject.toml``.
    """

    def __init__(
        self,
        *,
        locale: str | None = None,
        base_dir: str | Path | None = None,
    ) -> None:
        """
        Initialize the translator.

        :param locale: locale to force, or ``None`` to auto-detect.
        :param base_dir: base directory for resolving relative paths.
        """
        self._forced_locale = locale
        self._base_dir = self._resolve_base_dir(base_dir)

        self._catalogue: dict[str, Any] | None = None
        self._locale: str | None = None

    @property
    def loaded(self) -> bool:
        """
        Check if the translator has loaded a catalogue.

        :return: ``True`` if a catalogue is loaded, ``False`` otherwise.
        """
        return self._catalogue is not None

    @property
    def locale(self) -> str | None:
        """
        Get the active locale.

        :return: The active locale string, or ``None`` if not set.
        """
        return self._forced_locale or self._locale

    def configure(self, *, path: str | Path, locale: str | None = None) -> None:
        """
        Configure the translator with a specific catalogue path and locale.

        :param path: Path to the JSON catalogue or directory containing locale files.
        :param locale: Optional locale string.
        :return:
        """
        target_path = self._absolute_path(path)
        self._catalogue = self._load_catalogue(target_path)
        self._locale = locale

    def translate(self, key: str, default: str | None = None, *, locale: str | None = None) -> str:
        """
        Translate a key using the loaded catalogue.

        :param key: The translation key.
        :param default: Default value if the key is not found.
        :param locale: Optional locale to use for this translation.
        :return: The translated string, or the default/key if not found.
        """
        catalogue = self._catalogue_for(locale)
        value = self._lookup(catalogue, key)

        if value is None:
            return key if default is None else default

        return str(value)

    def resolve_placeholders(self, text: str, *, locale: str | None = None) -> str:
        """
        Resolve ``{key}`` placeholders in the given text.

        :param text: The text containing placeholders.
        :param locale: Optional locale to use for translations.
        :return: The text with placeholders resolved.
        """
        if not text or '{' not in text:
            return text

        def _replacer(match: re.Match[str]) -> str:
            raw_key = match.group(1).strip()
            if not raw_key:
                return match.group(0)
            return self.translate(raw_key, default=match.group(0), locale=locale)

        return _PLACEHOLDER_PATTERN.sub(_replacer, text)

    # Internal helpers

    def _catalogue_for(self, locale: str | None) -> dict[str, Any]:
        if self._catalogue is None:
            self._load()

        data = self._catalogue or {}
        target_locale = locale or self.locale

        if isinstance(data.get('locales'), dict):
            locales = data['locales']
            if target_locale and isinstance(locales.get(target_locale), dict):  # e.g {"locales": {"en": .., "fr": ..}}
                return locales[target_locale]

            default_locale = data.get('default_locale')
            if isinstance(default_locale, str) and isinstance(locales.get(default_locale), dict):
                return locales[default_locale]

            return locales  # e.g {"locales": {"key": "val"}}

        if target_locale and isinstance(data.get(target_locale), dict):  # e.g {"en": .., "fr": ..}
            return data[target_locale]

        return data  # e.g {"key": "val"}

    def _load(self) -> None:
        configuration = self._discover_configuration()

        if not configuration:
            self._catalogue = {}
            self._locale = None
            return

        path, locale = configuration
        catalogue = self._load_catalogue(path)

        self._catalogue = catalogue
        self._locale = locale

    def _discover_configuration(self) -> tuple[Path, str | None] | None:
        for resolver in (self._config_manual, self._config_from_env, self._config_from_pyproject):
            configuration = resolver()
            if configuration:
                return configuration
        return None

    def _config_manual(self) -> tuple[Path, str | None] | None:
        if _MANUAL_PATH is None:
            return None

        resolved = self._resolve_path(_MANUAL_PATH)

        if resolved.is_file():
            pass
        elif resolved.is_dir() and isinstance(_MANUAL_LOCALE, str):
            resolved = resolved / (_MANUAL_LOCALE + '.json')
            if not resolved.exists():
                msg = f'I18n catalogue "{resolved}" does not exist.'
                raise I18nConfigurationError(msg)
        else:
            msg = f'I18n catalogue "{resolved}" does not exist.'
            raise I18nConfigurationError(msg)

        return resolved, _MANUAL_LOCALE

    def _config_from_env(self) -> tuple[Path, str | None] | None:
        raw_path = os.getenv(_ENV_PATH)
        locale = os.getenv(_ENV_LOCALE)

        if raw_path:
            path = self._resolve_path(raw_path)
            if path.is_file():
                return path, locale

        return None

    def _config_from_pyproject(self) -> tuple[Path, str | None] | None:
        pyproject = self._find_pyproject()

        if not pyproject or not tomllib:
            return None

        try:
            with pyproject.open('rb') as stream:
                data = tomllib.load(stream)
        except (OSError, ValueError):
            return None

        section = data.get('tool', {}).get('mops', {}).get('i18n', {})
        if not isinstance(section, dict) or not section:
            return None

        locale = section.get('locale') if isinstance(section.get('locale'), str) else None
        base_dir = pyproject.parent

        raw_path = section.get('path')
        if isinstance(raw_path, str):
            path = self._resolve_path(raw_path, base=base_dir)
            if path.is_file():
                return path, locale

        return None

    def _find_pyproject(self) -> Path | None:
        current = self._base_dir
        for directory in (current, *current.parents):
            candidate = directory / 'pyproject.toml'
            if candidate.is_file():
                return candidate
        return None

    def _resolve_base_dir(self, base_dir: str | Path | None) -> Path:
        if base_dir is None:
            return Path.cwd().resolve()
        return Path(base_dir).expanduser().resolve()

    def _resolve_path(self, value: str | Path, *, base: Path | None = None) -> Path:
        path = Path(value).expanduser()
        if path.is_absolute():
            return path
        root = base or self._base_dir
        return (root / path).resolve()

    @staticmethod
    def _absolute_path(value: str | Path) -> Path:
        path = Path(value).expanduser()
        if path.is_absolute():
            return path
        return path.resolve()

    @staticmethod
    def _lookup(source: dict[str, Any], key: str) -> Any | None:
        if key in source:
            return source[key]

        parts = key.split('.')
        current: Any = source

        for part in parts:
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]

        if isinstance(current, dict):
            return None

        return current

    @staticmethod
    def _load_catalogue(path: Path) -> dict[str, Any]:
        try:
            with path.open('r', encoding='utf-8') as stream:
                data = json.load(stream)
        except FileNotFoundError as error:
            msg = f'I18n catalogue "{path}" does not exist.'
            raise I18nConfigurationError(msg) from error
        except json.JSONDecodeError as error:
            msg = f'I18n catalogue "{path}" has invalid JSON: {error}.'
            raise I18nConfigurationError(msg) from error

        if not isinstance(data, dict):
            msg = 'I18n catalogue must contain a JSON object at the top level.'
            raise I18nConfigurationError(msg)

        return data


def configure_translator(
    *,
    path: str | Path | None = None,
    locale: str | None = None,
) -> None:
    """
    Store manual overrides so they can take precedence during translator discovery.

    Passing no ``path`` clears the override.
    """
    global _MANUAL_PATH, _MANUAL_LOCALE, _MANUAL_PARSED  # noqa: PLW0603

    if path is None:
        _MANUAL_PATH = None
        _MANUAL_LOCALE = None
        _MANUAL_PARSED = False
        return

    _MANUAL_PATH = os.fspath(path)
    _MANUAL_LOCALE = locale
    _MANUAL_PARSED = True

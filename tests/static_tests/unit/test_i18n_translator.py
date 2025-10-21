from __future__ import annotations
import json
import textwrap

import pytest

from mops.utils import i18n_translator as i18n


def _write_catalogue(destination, name, data):
    path = destination / name
    path.write_text(json.dumps(data), encoding='utf-8')
    return path


def get_test_data():
    return {
        'button': {
            'text': 'Submit'  # inner attr
        },
        'title': 'Test'  # outer attr
    }


def test_resolve_from_envs(monkeypatch, tmp_path):
    catalogue = {
        'locales': {
            'fr': {'title': 'French'},
            'en': {'title': 'English'},
        }
    }
    path_catalogue = _write_catalogue(tmp_path, 'env_path.json', catalogue)
    monkeypatch.setenv('MOPS_I18N_PATH', str(path_catalogue))
    monkeypatch.setenv('MOPS_I18N_LOCALE', 'fr')

    assert i18n.I18nTranslator().translate('title') == 'French'


def test_resolve_from_pyproject_path(tmp_path):
    config_dir = tmp_path / 'config'
    config_dir.mkdir()
    _write_catalogue(config_dir, 'translations.json', get_test_data())

    pyproject = tmp_path / 'pyproject.toml'
    pyproject.write_text(
        textwrap.dedent(
            '''
            [tool.mops.i18n]
            path = "config/translations.json"
            locale = "fr"
            '''
        ),
        encoding='utf-8',
    )
    translator = i18n.I18nTranslator(base_dir=tmp_path)

    assert translator.translate('title') == 'Test'
    assert translator.locale == 'fr'


def test_missing_configuration_returns_key(tmp_path):
    translator = i18n.I18nTranslator(base_dir=tmp_path)

    assert translator.translate('title') == 'title'


def test_cli_configuration_overrides_other_sources(tmp_path):
    catalogue = tmp_path / 'cli.json'
    catalogue.write_text(json.dumps({'title': 'From CLI'}), encoding='utf-8')

    i18n.configure_translator(path=str(catalogue), locale='fr')
    translator = i18n.I18nTranslator()

    assert translator.translate('title') == 'From CLI'
    assert translator.locale == 'fr'


def test_cli_configuration_requires_existing_file(tmp_path):
    missing = tmp_path / 'does-not-exist.json'
    i18n.configure_translator(path=str(missing))

    translator = i18n.I18nTranslator()
    with pytest.raises(i18n.I18nConfigurationError):
        translator.translate('title')

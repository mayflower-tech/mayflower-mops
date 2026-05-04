from __future__ import annotations

import json
from pathlib import Path

import pytest

from mops.base.element import Element
from mops.mixins.objects.locator import Locator


@pytest.fixture(autouse=True)
def reset_element_translator():
    Element._translator = None
    yield
    Element._translator = None


def get_test_data():
    return {
        'button': {
            'text': 'Submit'  # inner attr
        },
        'title': 'Test'  # outer attr
    }


@pytest.fixture
def i18n_file(tmp_path):
    yield _write_catalogue(tmp_path, get_test_data())


def _write_catalogue(tmp_path: Path, data: dict) -> Path:
    file_path = tmp_path / 'i18n.json'
    file_path.write_text(json.dumps(data), encoding='utf-8')
    return file_path


@pytest.mark.parametrize(
    'locator, value',
    (
            ('button.text', 'button.text'),
            ('title', 'title'),
            (Locator(default='button.text'), 'button.text'),
            (Locator(default='title'), 'title'),
    )
)
def test_use_original_text_without_placeholders(tmp_path, i18n_file, locator, value):
    Element.configure_translator(path=i18n_file)
    element = Element(locator, name='submit button')

    if isinstance(locator, Locator):
        assert element.locator.default == value
    else:
        assert element.locator == value


@pytest.mark.parametrize(
    'locator, value',
    (
            ('{button.text}', get_test_data()['button']['text']),
            ('{title}', get_test_data()['title']),
            (Locator(default='{button.text}'), get_test_data()['button']['text']),
            (Locator(default='{title}'), get_test_data()['title']),
    )
)
def test_prepare_locator_replaces_placeholders(tmp_path, i18n_file, locator, value):
    Element.configure_translator(path=i18n_file)
    element = Element(locator, name='submit locator')

    if isinstance(locator, Locator):
        assert element.locator.default == value
    else:
        assert element.locator == value


def test_get_translated_text_returns_original_when_not_configured():
    element = Element('{button.text}', name='sample')
    assert element.locator == '{button.text}'


def test_get_translated_text_returns_original_when_forced_to_avoid(i18n_file):
    Element.configure_translator(path=i18n_file)
    element = Element('{button.text}', name='sample', avoid_translation=True)
    assert element.locator == '{button.text}'

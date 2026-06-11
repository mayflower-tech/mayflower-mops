from __future__ import annotations

import re

from mops.self_healing.snapshot import ElementSnapshot, JsonFileSnapshotStorage

# ---------------------------------------------------------------------------
# normalize_locator_key
# ---------------------------------------------------------------------------


def test_normalize_locator_key_preserves_clean_key():
    """Locator without dynamic data stays unchanged."""
    storage = JsonFileSnapshotStorage()
    assert storage.normalize_locator_key('MyElement::.row') == 'MyElement::.row'


def test_normalize_locator_key_strips_numeric_id_suffix():
    r"""``#user-12345`` → ``#user``  (rule: id, -\d+$  — the ``-`` is part of the match)."""
    storage = JsonFileSnapshotStorage()
    assert storage.normalize_locator_key('MyElement::#user-12345') == 'MyElement::#user'


def test_normalize_locator_key_purely_numeric_id_rule_skipped():
    r"""``^\d+$`` is anchor-bound, it won't match mid-string in a flat key — expected."""
    storage = JsonFileSnapshotStorage()
    # A locator like #12345 does NOT get normalized by the ^\d+$ rule
    assert storage.normalize_locator_key('MyElement::#12345') == 'MyElement::#12345'


def test_normalize_locator_key_vue_rule_skipped_mid_string():
    r"""``^data-v-`` is anchor-bound, doesn't match mid-string — expected."""
    storage = JsonFileSnapshotStorage()
    result = storage.normalize_locator_key('MyElement::[data-v-abc123]')
    assert 'data-v-abc123' in result


def test_normalize_locator_key_class_token_removal_rules_skipped():
    """Token-removal rules (replacement=None) are not applied to locator keys."""
    storage = JsonFileSnapshotStorage()
    result = storage.normalize_locator_key('MyElement::.btn.active')
    assert 'active' in result


# ---------------------------------------------------------------------------
# _normalize_attrs — class token removal
# ---------------------------------------------------------------------------


def test_normalize_attrs_removes_css_module_hash_from_class():
    """Button_nameHash__xy tokens removed from class attribute."""
    storage = JsonFileSnapshotStorage()
    attrs = {'class': 'Button_1a2b3__xy another-class'}
    result = storage._normalize_attrs(attrs)
    assert result['class'] == 'another-class'


def test_normalize_attrs_removes_hash_suffix_from_class():
    r"""``#sb`` / ``#rdT`` tokens removed from class."""
    storage = JsonFileSnapshotStorage()
    attrs = {'class': 'some-class #sb'}
    result = storage._normalize_attrs(attrs)
    assert result['class'] == 'some-class'


def test_normalize_attrs_removes_dynamic_state_classes():
    """Exact-match state tokens (active / disabled / selected / open / closed) removed."""
    storage = JsonFileSnapshotStorage()
    attrs = {'class': 'btn active disabled js-toggle'}
    result = storage._normalize_attrs(attrs)
    assert result['class'] == 'btn js-toggle'


def test_normalize_attrs_preserves_normal_class():
    """Meaningful class names survive."""
    storage = JsonFileSnapshotStorage()
    attrs = {'class': 'btn btn-primary header'}
    result = storage._normalize_attrs(attrs)
    assert result['class'] == 'btn btn-primary header'


# ---------------------------------------------------------------------------
# _normalize_attrs — id normalization
# ---------------------------------------------------------------------------


def test_normalize_attrs_removes_numeric_id():
    """``id='12345'`` is removed (entirely numeric)."""
    storage = JsonFileSnapshotStorage()
    attrs = {'id': '12345'}
    result = storage._normalize_attrs(attrs)
    assert 'id' not in result


def test_normalize_attrs_strips_numeric_id_suffix():
    r"""``id='user-12345'`` → ``id='user'`` (the ``-`` is part of the ``-\d+$`` match)."""
    storage = JsonFileSnapshotStorage()
    attrs = {'id': 'user-12345'}
    result = storage._normalize_attrs(attrs)
    assert result['id'] == 'user'


def test_normalize_attrs_preserves_meaningful_id():
    """``id='submit-btn'`` stays."""
    storage = JsonFileSnapshotStorage()
    attrs = {'id': 'submit-btn'}
    result = storage._normalize_attrs(attrs)
    assert result['id'] == 'submit-btn'


# ---------------------------------------------------------------------------
# _normalize_attrs — Vue scoped data attributes
# ---------------------------------------------------------------------------


def test_normalize_attrs_removes_vue_data_attributes():
    """``data-v-*`` attributes removed regardless of value."""
    storage = JsonFileSnapshotStorage()
    attrs = {'data-v-abc123': '', 'data-v-def456': 'some-value', 'data-testid': 'submit'}
    result = storage._normalize_attrs(attrs)
    assert 'data-v-abc123' not in result
    assert 'data-v-def456' not in result
    assert result['data-testid'] == 'submit'


# ---------------------------------------------------------------------------
# _normalize_attrs — edge cases
# ---------------------------------------------------------------------------


def test_normalize_attrs_empty():
    """Empty dict stays empty."""
    storage = JsonFileSnapshotStorage()
    assert storage._normalize_attrs({}) == {}


def test_normalize_attrs_unknown_attrs_preserved():
    """Attributes without matching rules are preserved."""
    storage = JsonFileSnapshotStorage()
    attrs = {'aria-label': 'Close', 'role': 'button', 'data-test': 'submit'}
    result = storage._normalize_attrs(attrs)
    assert result == attrs


# ---------------------------------------------------------------------------
# _normalize_snapshot — full snapshot normalization
# ---------------------------------------------------------------------------


def test_normalize_snapshot_cleans_attrs_and_text():
    """Full snapshot normalization works across all fields."""
    storage = JsonFileSnapshotStorage()
    snapshot = ElementSnapshot(
        tag='button',
        attributes={
            'class': 'btn active #sb',
            'id': 'submit-42',
            'aria-label': 'Submit',
        },
        text='  Click  Me  ',
        parent_tag='form',
        parent_attributes={
            'class': 'form-wrapper js-form',
            'data-v-xyz': '',
        },
        siblings=[
            {'tag': 'span', 'text': 'Hint', 'attrs': {'class': 'helper #rdT'}},
        ],
    )
    result = storage._normalize_snapshot(snapshot)
    assert result.tag == 'button'
    # Class tokens cleaned (active and #sb removed)
    assert result.attributes['class'] == 'btn'
    # ID suffix stripped (the ``-`` is part of the match)
    assert result.attributes['id'] == 'submit'
    # Non-matching attrs preserved
    assert result.attributes['aria-label'] == 'Submit'
    # Text whitespace normalized
    assert result.text == 'Click Me'
    # Parent attrs cleaned
    # ``js-form`` is not an exact match for the ``^(js-|...)`` rule — kept
    assert result.parent_attributes['class'] == 'form-wrapper js-form'
    assert 'data-v-xyz' not in result.parent_attributes
    # Sibling attrs cleaned
    assert result.siblings[0]['attrs']['class'] == 'helper'


def test_normalize_snapshot_without_parent():
    """Snapshot with no parent does not crash."""
    storage = JsonFileSnapshotStorage()
    snapshot = ElementSnapshot(
        tag='div',
        attributes={'class': 'box'},
        text='content',
        parent_tag=None,
        parent_attributes={},
        siblings=[],
    )
    result = storage._normalize_snapshot(snapshot)
    assert result.parent_tag is None


# ---------------------------------------------------------------------------
# custom normalization rules
# ---------------------------------------------------------------------------


def test_custom_rules_extend_defaults():
    """External projects can extend default rules."""
    storage = JsonFileSnapshotStorage()
    storage.set_normalization_rules([
        *storage._normalization_rules,
        ('data-track', re.compile(r'.*'), ''),
    ])
    attrs = {'class': 'btn', 'data-track': 'some-value'}
    result = storage._normalize_attrs(attrs)
    assert result['class'] == 'btn'
    assert 'data-track' not in result


def test_custom_rules_apply_to_locator_key():
    """Custom string-replacement rules affect normalize_locator_key too."""
    storage = JsonFileSnapshotStorage()
    storage.set_normalization_rules([
        (None, re.compile(r'custom-'), ''),
    ])
    assert storage.normalize_locator_key('El::#custom-123') == 'El::#123'

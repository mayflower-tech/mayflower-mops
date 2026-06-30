import pytest

from mops.base.element import Element
from mops.self_healing import configure
from mops.self_healing.snapshot import JsonFileSnapshotStorage
from mops.self_healing.config import get_config


@pytest.fixture(autouse=True)
def setup():
    configure(save_snapshots=True, heal_locators=True, score_threshold=0.5, storage=JsonFileSnapshotStorage())
    yield
    configure(save_snapshots=False, heal_locators=False)


def test_self_healing_recovers_broken_locator(second_playground_page):
    """
    Self-healing finds row_with_cards when its locator is broken but snapshot exists.

    Flow:
    1. Enable self-healing and find the real element → snapshot saved as JSON.
    2. Seed the same snapshot under a broken locator key.
    3. Access a new element that uses the broken locator → healing kicks in and
       finds the element by DOM similarity, returning the correct node.
    """
    row = second_playground_page.row_with_cards

    # Find the real element so the snapshot is persisted.
    row.wait_visibility(silent=True)

    storage = get_config().storage  # same instance used by the healer
    real_key = f'{row.name}::{row.locator}'
    snapshot = storage.load(real_key)
    assert snapshot is not None, f'Snapshot was not saved for key: {real_key!r}'

    # Seed the snapshot under the broken locator so the healer can look it up.
    broken_locator = '.row-broken-locator-self-healing-test'
    storage.save(f'{row.name}::{broken_locator}', snapshot)

    # Create an element that uses the broken locator but shares the same name,
    # so the healer finds the snapshot and can attempt recovery.
    broken_row = Element(broken_locator, name=row.name)

    # get_attribute → .element property → _get_element → _find_element.
    # The broken locator fails, is_healing_enabled() is True (no @no_healing here),
    # so the healer runs and returns the real .row element.
    cls = broken_row.get_attribute('class', silent=True)

    assert cls is not None, 'Self-healing did not recover the element'
    assert 'row' in cls


def test_self_healing_recovery_after_class_change(second_playground_page):
    """
    Self-healing recovers an element whose class was changed in DOM.

    Flow:
    1. Find row_with_cards → snapshot saved.
    2. Change the ``class`` attribute via JS, breaking the ``.row`` locator.
    3. Create a new element with the broken locator.
    4. ``wait_visibility`` triggers polling → healing finds the element
       by DOM similarity (snapshot matching).
    """
    row = second_playground_page.row_with_cards

    # Find the real element so the snapshot is persisted
    row.wait_visibility(silent=True)

    storage = get_config().storage
    real_key = f'{row.name}::{row.locator}'
    assert storage.load(real_key) is not None

    # Break the locator by changing the class of ALL .row elements
    driver = second_playground_page.driver
    driver.execute_script("""
        var elements = document.querySelectorAll('.row');
        for (var i = 0; i < elements.length; i++) {
            elements[i].className = 'broken-row';
        }
    """)

    # wait_visibility triggers element lookup → healing should recover
    row.wait_visibility(silent=True)

    cls = row.get_attribute('class', silent=True)
    assert cls is not None, 'Self-healing did not recover the element'
    assert 'broken-row' in cls


def test_self_healing_falls_back_to_second_locator(second_playground_page):
    """
    When the first healed locator fails to find the element,
    ``_find_element`` tries subsequent locators from ``healed_locators_candidates``.

    Flow:
    1. Find row_with_cards → snapshot saved.
    2. Change the ``class`` in DOM, breaking the original ``.row`` locator.
    3. Patch ``generate_locator`` to prepend a non-existent locator so the
       first attempt always fails.
    4. Healing runs → first locator misses → second (real) locator succeeds.
    """
    from unittest.mock import patch

    import mops.self_healing.healer as healer_module

    row = second_playground_page.row_with_cards
    row.wait_visibility(silent=True)  # snapshot saved

    # Break the original locator
    driver = second_playground_page.driver
    driver.execute_script("""
        var elements = document.querySelectorAll('.row');
        for (var i = 0; i < elements.length; i++) {
            elements[i].className = 'broken-row';
        }
    """)

    original_generate = healer_module.generate_locator

    def _generate_with_bad_first(web_element, driver):
        real_locators = original_generate(web_element, driver)
        return ['xpath=//*[@id="definitely-not-found"]'] + real_locators

    with patch('mops.self_healing.healer.generate_locator', side_effect=_generate_with_bad_first):
        cls = row.get_attribute('class', silent=True)
        assert cls is not None, 'Self-healing did not recover the element'
        assert 'broken-row' in cls


def test_wait_hidden_does_not_heal(second_playground_page):
    """
    ``wait_hidden`` must NOT trigger self-healing.

    Flow:
    1. Find row_with_cards → snapshot saved.
    2. Seed the snapshot under a broken locator key.
    3. Create a new element with the broken locator.
    4. ``wait_hidden`` succeeds immediately (element not found = hidden).
    5. Assert the locator was NOT updated — healing was never attempted.
    6. Assert the element still can't be found after ``wait_hidden``.
    """
    from unittest.mock import patch

    from mops.selenium.core.core_element import CoreElement

    row = second_playground_page.row_with_cards

    # Find the real element so the snapshot is persisted.
    row.wait_visibility(silent=True)

    storage = get_config().storage
    real_key = f'{row.name}::{row.locator}'
    snapshot = storage.load(real_key)
    assert snapshot is not None

    # Seed the snapshot under a broken locator.
    broken_locator = '.row-broken-locator-self-healing-test'
    storage.save(f'{row.name}::{broken_locator}', snapshot)

    broken_row = Element(broken_locator, name=row.name)

    # Spy on _attempt_healing — it must NOT be called during wait_hidden.
    original_attempt = CoreElement._attempt_healing
    attempt_called = False

    def _spy(self, *args, **kwargs):
        nonlocal attempt_called
        attempt_called = True
        return original_attempt(self, *args, **kwargs)

    with patch.object(CoreElement, '_attempt_healing', _spy):
        broken_row.wait_hidden(silent=True)

    # wait_hidden should succeed without attempting healing
    assert not attempt_called, '_attempt_healing was called during wait_hidden'
    assert broken_row.locator == broken_locator, 'Locator was changed by healing'

    # Verify the element can't be found with the broken locator
    assert not broken_row.is_available(), 'Broken locator should not find an element'


def test_is_displayed_does_not_heal(second_playground_page):
    """
    ``is_displayed`` must NOT trigger self-healing.

    Flow:
    1. Find row_with_cards → snapshot saved.
    2. Seed the snapshot under a broken locator key.
    3. Create a new element with the broken locator.
    4. ``is_displayed`` returns False (element not found).
    5. Assert ``_attempt_healing`` was never called.
    """
    from unittest.mock import patch

    from mops.selenium.core.core_element import CoreElement

    row = second_playground_page.row_with_cards
    row.wait_visibility(silent=True)

    storage = get_config().storage
    real_key = f'{row.name}::{row.locator}'
    snapshot = storage.load(real_key)

    broken_locator = '.row-broken-locator-self-healing-test'
    storage.save(f'{row.name}::{broken_locator}', snapshot)

    broken_row = Element(broken_locator, name=row.name)

    original_attempt = CoreElement._attempt_healing
    attempt_called = False

    def _spy(self, *args, **kwargs):
        nonlocal attempt_called
        attempt_called = True
        return original_attempt(self, *args, **kwargs)

    with patch.object(CoreElement, '_attempt_healing', _spy):
        displayed = broken_row.is_displayed(silent=True)

    assert not displayed, 'Broken element should not be displayed'
    assert not attempt_called, '_attempt_healing was called during is_displayed'
    assert broken_row.locator == broken_locator, 'Locator was changed by healing'


def test_is_hidden_does_not_heal(second_playground_page):
    """
    ``is_hidden`` must NOT trigger self-healing.

    Flow:
    1. Find row_with_cards → snapshot saved.
    2. Seed the snapshot under a broken locator key.
    3. Create a new element with the broken locator.
    4. ``is_hidden`` returns True (element not found = hidden).
    5. Assert ``_attempt_healing`` was never called.
    """
    from unittest.mock import patch

    from mops.selenium.core.core_element import CoreElement

    row = second_playground_page.row_with_cards
    row.wait_visibility(silent=True)

    storage = get_config().storage
    real_key = f'{row.name}::{row.locator}'
    snapshot = storage.load(real_key)

    broken_locator = '.row-broken-locator-self-healing-test'
    storage.save(f'{row.name}::{broken_locator}', snapshot)

    broken_row = Element(broken_locator, name=row.name)

    original_attempt = CoreElement._attempt_healing
    attempt_called = False

    def _spy(self, *args, **kwargs):
        nonlocal attempt_called
        attempt_called = True
        return original_attempt(self, *args, **kwargs)

    with patch.object(CoreElement, '_attempt_healing', _spy):
        hidden = broken_row.is_hidden(silent=True)

    assert hidden, 'Broken element should be considered hidden'
    assert not attempt_called, '_attempt_healing was called during is_hidden'
    assert broken_row.locator == broken_locator, 'Locator was changed by healing'


def test_wait_hidden_without_error_does_not_heal(second_playground_page):
    """
    ``wait_hidden_without_error`` must NOT trigger self-healing.

    Flow:
    1. Find row_with_cards → snapshot saved.
    2. Seed the snapshot under a broken locator key.
    3. Create a new element with the broken locator.
    4. ``wait_hidden_without_error`` succeeds (element not found = hidden).
    5. Assert ``_attempt_healing`` was never called.
    """
    from unittest.mock import patch

    from mops.selenium.core.core_element import CoreElement

    row = second_playground_page.row_with_cards
    row.wait_visibility(silent=True)

    storage = get_config().storage
    real_key = f'{row.name}::{row.locator}'
    snapshot = storage.load(real_key)

    broken_locator = '.row-broken-locator-self-healing-test'
    storage.save(f'{row.name}::{broken_locator}', snapshot)

    broken_row = Element(broken_locator, name=row.name)

    original_attempt = CoreElement._attempt_healing
    attempt_called = False

    def _spy(self, *args, **kwargs):
        nonlocal attempt_called
        attempt_called = True
        return original_attempt(self, *args, **kwargs)

    with patch.object(CoreElement, '_attempt_healing', _spy):
        broken_row.wait_hidden_without_error(silent=True)

    assert not attempt_called, '_attempt_healing was called during wait_hidden_without_error'
    assert broken_row.locator == broken_locator, 'Locator was changed by healing'


def test_wait_hidden_without_error_timeout_does_not_heal(second_playground_page):
    """
    ``wait_hidden_without_error`` must NOT heal when the element IS invisible
    and the wait succeeds.

    Flow:
    1. Find row_with_cards → snapshot saved.
    2. Hide the element via JS.
    3. Spy on ``_attempt_healing`` and ``_heal_after_wait``.
    4. ``wait_hidden_without_error`` succeeds (element is hidden).
    5. Assert neither healing method was called.
    """
    from unittest.mock import patch

    from mops.selenium.core.core_element import CoreElement

    row = second_playground_page.row_with_cards
    row.wait_visibility(silent=True)  # snapshot saved

    # Hide the element
    row.driver_wrapper.execute_script('arguments[0].style.display = "none";', row)

    original_attempt = CoreElement._attempt_healing
    attempt_called = False
    original_heal_after = CoreElement._heal_after_wait
    heal_after_called = False

    def _spy_attempt(self, *args, **kwargs):
        nonlocal attempt_called
        attempt_called = True
        return original_attempt(self, *args, **kwargs)

    def _spy_heal_after(self, *args, **kwargs):
        nonlocal heal_after_called
        heal_after_called = True
        return original_heal_after(self, *args, **kwargs)

    with patch.object(CoreElement, '_attempt_healing', _spy_attempt), \
         patch.object(CoreElement, '_heal_after_wait', _spy_heal_after):
        row.wait_hidden_without_error(silent=True)

    assert not attempt_called, \
        '_attempt_healing was called during wait_hidden_without_error'
    assert not heal_after_called, \
        '_heal_after_wait was called during wait_hidden_without_error'
    # Verify element actually is hidden
    assert row.is_hidden(silent=True), 'Element should be hidden'


def test_wait_visibility_without_error_does_not_heal(second_playground_page):
    """
    ``wait_visibility_without_error`` must NOT heal when the element is
    invisible and the wait times out.

    Flow:
    1. Find row_with_cards → snapshot saved.
    2. Hide the element via JS so it's not visible.
    3. Spy on ``_attempt_healing`` and ``_heal_after_wait``.
    4. ``wait_visibility_without_error`` times out (element is hidden).
    5. Assert neither healing method was called.
    """
    from unittest.mock import patch

    from mops.selenium.core.core_element import CoreElement

    row = second_playground_page.row_with_cards
    row.wait_visibility(silent=True)  # snapshot saved

    # Hide the element so wait_visibility will time out
    row.driver_wrapper.execute_script('arguments[0].style.display = "none";', row)

    original_attempt = CoreElement._attempt_healing
    attempt_called = False
    original_heal_after = CoreElement._heal_after_wait
    heal_after_called = False

    def _spy_attempt(self, *args, **kwargs):
        nonlocal attempt_called
        attempt_called = True
        return original_attempt(self, *args, **kwargs)

    def _spy_heal_after(self, *args, **kwargs):
        nonlocal heal_after_called
        heal_after_called = True
        return original_heal_after(self, *args, **kwargs)

    with patch.object(CoreElement, '_attempt_healing', _spy_attempt), \
         patch.object(CoreElement, '_heal_after_wait', _spy_heal_after):
        row.wait_visibility_without_error(silent=True)

    assert not attempt_called, \
        '_attempt_healing was called during wait_visibility_without_error'
    assert not heal_after_called, \
        '_heal_after_wait was called during wait_visibility_without_error'
    # Verify element actually is not visible
    assert not row.is_displayed(silent=True), 'Element should not be visible'


def test_parent_healing_not_triggered_during_child_healing(second_playground_page):
    """
    Self-healing on a child must NOT trigger healing on its parent.

    Flow:
    1. Create parent and child elements. Find child → snapshot saved.
    2. Seed the snapshot under a broken child locator.
    3. Create new child with broken locator, same parent.
    4. Spy on ``_attempt_healing`` for all CoreElement instances.
    5. ``get_attribute`` on the broken child → child heals.
    6. Assert child locator was updated.
    7. Assert parent ``_attempt_healing`` was NEVER called.
    """
    from unittest.mock import patch

    from mops.selenium.core.core_element import CoreElement

    row = second_playground_page.row_with_cards

    # Create a child with the row as its parent
    parent = row
    child_with_parent = Element('a', name='card link', parent=parent)

    # Find child → snapshot saved (both parent and child snapshots)
    child_with_parent.wait_visibility(silent=True)

    storage = get_config().storage
    # Key includes parent: "card link::a -> row with cards::.row"
    parent_key_part = f'{child_with_parent.name}::{child_with_parent.locator}'
    if child_with_parent.parent:
        parent_key_part += f' -> {row.name}::{row.locator}'
    real_key = parent_key_part
    snapshot = storage.load(real_key)
    assert snapshot is not None

    # Seed snapshot under a broken child locator (same parent hierarchy)
    broken_locator = '.broken-card-link'
    broken_key = f'{child_with_parent.name}::{broken_locator}'
    if child_with_parent.parent:
        broken_key += f' -> {row.name}::{row.locator}'
    storage.save(broken_key, snapshot)

    broken_child = Element(broken_locator, name=child_with_parent.name, parent=row)

    # Spy on _attempt_healing for all instances
    attempt_calls_names = []
    original_attempt = CoreElement._attempt_healing

    def _spy(self, *args, **kwargs):
        attempt_calls_names.append(self.name)
        return original_attempt(self, *args, **kwargs)

    with patch.object(CoreElement, '_attempt_healing', _spy):
        cls = broken_child.get_attribute('class', silent=True)

    assert cls is not None, 'Child was not healed'
    assert broken_child.locator != broken_locator, 'Child locator was not healed'
    # Parent name must NOT appear in healing calls
    assert parent.name not in attempt_calls_names, \
        f'Parent healing was triggered: {attempt_calls_names}'

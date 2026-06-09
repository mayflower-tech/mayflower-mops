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

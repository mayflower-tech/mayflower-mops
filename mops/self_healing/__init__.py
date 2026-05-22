"""Self-healing locators for MOPS.

Quick start::

    from mops.self_healing import configure
    configure(enabled=True, score_threshold=0.75)

You can also supply a custom storage backend::

    from mops.self_healing import configure, JsonFileSnapshotStorage
    configure(enabled=True, storage=JsonFileSnapshotStorage('my_snapshots'))
"""

from mops.self_healing.config import configure, get_config
from mops.self_healing.context import is_healing_enabled, no_healing
from mops.self_healing.healer import Healer, HealingResult
from mops.self_healing.snapshot import ElementSnapshot, JsonFileSnapshotStorage, SnapshotStorage

__all__ = [
    'ElementSnapshot',
    'Healer',
    'HealingResult',
    'JsonFileSnapshotStorage',
    'SnapshotStorage',
    'configure',
    'get_config',
    'is_healing_enabled',
    'no_healing',
]

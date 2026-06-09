from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mops.self_healing.snapshot import SnapshotStorage


@dataclass
class SelfHealingConfig:
    """Configuration for self-healing locators.

    :param save_snapshots: When :obj:`True`, snapshots of successfully located elements
        are saved to storage for future healing.
    :param heal_locators: When :obj:`True`, the system attempts to heal broken locators
        by loading saved snapshots and searching for matching elements.
    :param score_threshold: Minimum similarity score (0–1) to accept a healed locator.
    :param storage: A :class:`SnapshotStorage` instance. When not set, storage
        remains uninitialised and neither snapshots nor healing will work.
        External projects can pass their own backend (Redis, S3, PostgreSQL, etc.) here.
    """

    save_snapshots: bool = False
    heal_locators: bool = False
    score_threshold: float = 0.7
    storage: SnapshotStorage | None = None


_config = SelfHealingConfig()


def configure(**kwargs: object) -> None:
    """Update the global self-healing config.

    Example::

        from mops.self_healing import configure, JsonFileSnapshotStorage

        # Save snapshots but don't heal (data collection)
        configure(save_snapshots=True)

        # Full healing: save snapshots AND heal broken locators
        configure(
            save_snapshots=True,
            heal_locators=True,
            score_threshold=0.75,
            storage=JsonFileSnapshotStorage('my_snapshots'),
        )

        # Custom backend
        configure(storage=MyCustomStorage())
    """
    for key, value in kwargs.items():
        setattr(_config, key, value)


def get_config() -> SelfHealingConfig:
    """Return the current global self-healing config."""
    return _config

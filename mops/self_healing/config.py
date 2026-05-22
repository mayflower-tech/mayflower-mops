from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mops.self_healing.snapshot import SnapshotStorage


@dataclass
class SelfHealingConfig:
    """Configuration for self-healing locators.

    :param enabled: Enable or disable self-healing globally.
    :param score_threshold: Minimum similarity score (0–1) to accept a healed locator.
    :param storage_directory: Directory path for storing element snapshot JSON files.
        Ignored when *storage* is provided.
    :param storage: A custom :class:`SnapshotStorage` instance. When set, this
        overrides *storage_directory*. External projects can pass their own
        storage backend (e.g. Redis, S3, PostgreSQL) here.
    """

    enabled: bool = False
    score_threshold: float = 0.7
    storage_directory: str = '.self_healing_snapshots'
    storage: SnapshotStorage | None = None


_config = SelfHealingConfig()


def configure(**kwargs: object) -> None:
    """Update the global self-healing config.

    Example::

        from mops.self_healing import configure
        configure(enabled=True, score_threshold=0.8, storage_directory='snapshots')
        configure(storage=MyCustomStorage())  # custom backend
    """
    for key, value in kwargs.items():
        setattr(_config, key, value)


def get_config() -> SelfHealingConfig:
    """Return the current global self-healing config."""
    return _config

from __future__ import annotations

from typing import TYPE_CHECKING

from mops.self_healing.config import get_config
from mops.self_healing.healer import Healer

if TYPE_CHECKING:
    from mops.self_healing.snapshot import SnapshotStorage


class _HealerState:
    """Module-level state for the healer singleton."""

    storage: SnapshotStorage | None = None
    healer: Healer | None = None


def get_healer() -> Healer:
    """Return the global Healer singleton.

    Re-initialises when ``get_config().storage`` changes (identity check)
    or when the cached storage is ``None``, so that ``configure()`` calls
    between tests are picked up.
    """
    config = get_config()

    if _HealerState.healer and _HealerState.storage is config.storage and _HealerState.storage is not None:
        return _HealerState.healer

    _HealerState.storage = config.storage
    _HealerState.healer = Healer(
        _HealerState.storage,
        config.score_threshold,
        scoring_weights=config.scoring_weights,
        on_healing_failure=config.on_healing_failure,
    )
    return _HealerState.healer

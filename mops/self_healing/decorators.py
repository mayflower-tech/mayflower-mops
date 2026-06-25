from __future__ import annotations

from contextlib import suppress
from functools import wraps
from typing import TYPE_CHECKING, Any

from mops.exceptions import NoSuchElementException
from mops.self_healing.config import get_config

if TYPE_CHECKING:
    from collections.abc import Callable


def healing(method: Callable) -> Callable:
    """Attempt self-healing when a :class:`NoSuchElementException` is raised.

    Apply to element access methods (``_get_element``, ``click``, etc.)
    so that direct element lookups are healed immediately.
    """

    @wraps(method)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return method(self, *args, **kwargs)
        except NoSuchElementException:
            if not get_config().heal_locators:
                raise
            result = self._attempt_healing()
            if not result:
                raise
            return self._try_healed_locators(result)

    return wrapper


def healing_after_wait(method: Callable) -> Callable:
    """Attempt self-healing after a wait condition times out.

    If the wait times out (the exception carries a ``_timeout`` attribute),
    calls ``_heal_after_wait()`` once and retries the wait on success.
    """

    @wraps(method)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return method(self, *args, **kwargs)
        except Exception as exc:
            if getattr(exc, '_timeout', None) is not None:
                heal = getattr(self, '_heal_after_wait', None)
                if heal and heal():
                    with suppress(Exception):
                        return method(self, *args, **kwargs)
            raise

    return wrapper

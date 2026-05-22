from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any


@dataclass
class ElementSnapshot:
    """Snapshot of a successfully located element's DOM context."""

    tag: str
    attributes: dict[str, str]
    text: str
    parent_tag: str | None
    parent_attributes: dict[str, str]
    siblings: list[dict[str, Any]]


_MAX_FILENAME_LENGTH = 200
_FILENAME_HASH_SUFFIX_LENGTH = 12

_GET_ELEMENT_SNAPSHOT_JS = """
return (function(el) {
    function getAttrs(node) {
        var attrs = {};
        for (var i = 0; i < node.attributes.length; i++) {
            attrs[node.attributes[i].name] = node.attributes[i].value;
        }
        return attrs;
    }
    var parent = el.parentElement;
    var parentTag = null;
    var parentAttrs = {};
    var siblings = [];
    if (parent) {
        parentTag = parent.tagName.toLowerCase();
        parentAttrs = getAttrs(parent);
        var children = parent.children;
        for (var i = 0; i < children.length && siblings.length < 5; i++) {
            if (children[i] !== el) {
                siblings.push({
                    tag: children[i].tagName.toLowerCase(),
                    text: (children[i].textContent || '').trim().substring(0, 50),
                    attrs: getAttrs(children[i])
                });
            }
        }
    }
    return {
        tag: el.tagName.toLowerCase(),
        attrs: getAttrs(el),
        text: (el.textContent || '').trim().substring(0, 100),
        parentTag: parentTag,
        parentAttrs: parentAttrs,
        siblings: siblings
    };
})(arguments[0]);
"""


class SnapshotStorage(ABC):
    """Abstract snapshot storage for element snapshots.

    Subclasses must implement :meth:`save` and :meth:`load`.
    The :meth:`save_from_element` method is concrete — it extracts DOM data
    from a live web element and delegates to :meth:`save` for persistence.
    """

    def __init__(self) -> None:
        self._saved_this_session: set[str] = set()

    def save_from_element(self, locator_key: str, web_element: object, driver: object) -> None:
        """Extract snapshot from a live web element and persist it."""
        if locator_key in self._saved_this_session:
            return

        try:
            raw = driver.execute_script(_GET_ELEMENT_SNAPSHOT_JS, web_element)
        except Exception:
            return

        snapshot = ElementSnapshot(
            tag=raw['tag'],
            attributes=raw['attrs'],
            text=raw['text'],
            parent_tag=raw['parentTag'],
            parent_attributes=raw['parentAttrs'],
            siblings=raw['siblings'],
        )

        self.save(locator_key, snapshot)
        self._saved_this_session.add(locator_key)

    @abstractmethod
    def save(self, locator_key: str, snapshot: ElementSnapshot) -> None:
        """Persist a snapshot."""

    @abstractmethod
    def load(self, locator_key: str) -> ElementSnapshot | None:
        """Load a previously saved snapshot."""


class JsonFileSnapshotStorage(SnapshotStorage):
    """Stores element snapshots as individual JSON files.

    Each snapshot is written to ``{directory}/{safe_filename}.json``.

    The JSON format is self-describing so that external projects can consume
    these files without any knowledge of MOPS internals::

        {
            "locator_key": "...",
            "snapshot": {
                "tag": "button",
                "attributes": {"id": "submit", ...},
                "text": "Submit",
                "parent_tag": "form",
                "parent_attributes": {"class": "login-form", ...},
                "siblings": [...]
            },
            "updated_at": "2026-05-22T12:00:00+00:00"
        }

    :param directory: Directory path for storing snapshot JSON files.
    """

    def __init__(self, directory: str = '.self_healing_snapshots') -> None:
        super().__init__()
        self._directory = Path(directory)
        self._directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _key_to_filename(locator_key: str) -> str:
        """Convert a locator key to a safe filesystem name."""
        safe = locator_key.replace('::', '__').replace('/', '_').replace('\\', '_')
        # Limit length to avoid filesystem issues
        if len(safe) > _MAX_FILENAME_LENGTH:
            suffix = hashlib.md5(locator_key.encode(), usedforsecurity=False).hexdigest()[:_FILENAME_HASH_SUFFIX_LENGTH]
            safe = safe[: _MAX_FILENAME_LENGTH - _FILENAME_HASH_SUFFIX_LENGTH - 2] + '__' + suffix
        return safe + '.json'

    def save(self, locator_key: str, snapshot: ElementSnapshot) -> None:
        """Persist a snapshot as a JSON file."""
        filepath = self._directory / self._key_to_filename(locator_key)
        data = {
            'locator_key': locator_key,
            'snapshot': asdict(snapshot),
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }
        with filepath.open('w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def load(self, locator_key: str) -> ElementSnapshot | None:
        """Load a snapshot by locator key from its JSON file."""
        filepath = self._directory / self._key_to_filename(locator_key)
        if not filepath.exists():
            return None
        try:
            with filepath.open(encoding='utf-8') as f:
                data = json.load(f)
            return ElementSnapshot(**data['snapshot'])
        except (json.JSONDecodeError, KeyError, FileNotFoundError):
            return None


class SqliteSnapshotStorage(SnapshotStorage):
    """SQLite-backed storage for element snapshots.

    .. note::
        This class is kept as a reference implementation for developers
        who want to write their own :class:`SnapshotStorage` subclass.
        The default storage is :class:`JsonFileSnapshotStorage`.
    """

    def __init__(self, db_path: str) -> None:
        super().__init__()
        self._db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    locator_key TEXT PRIMARY KEY,
                    snapshot_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def save(self, locator_key: str, snapshot: ElementSnapshot) -> None:
        """Persist a snapshot to the SQLite database."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                'INSERT OR REPLACE INTO snapshots (locator_key, snapshot_json, updated_at) VALUES (?, ?, ?)',
                (locator_key, json.dumps(asdict(snapshot)), datetime.now(timezone.utc).isoformat()),
            )
        self._saved_this_session.add(locator_key)

    def load(self, locator_key: str) -> ElementSnapshot | None:
        """Load a snapshot from the SQLite database."""
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                'SELECT snapshot_json FROM snapshots WHERE locator_key = ?',
                (locator_key,),
            ).fetchone()

        if not row:
            return None

        data = json.loads(row[0])
        return ElementSnapshot(**data)

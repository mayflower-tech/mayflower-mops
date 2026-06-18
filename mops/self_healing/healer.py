from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import TYPE_CHECKING, Any

from selenium.common.exceptions import WebDriverException
from selenium.webdriver.common.by import By

from mops.self_healing.locator_generator import generate_locator

if TYPE_CHECKING:
    from collections.abc import Callable

    from mops.self_healing.snapshot import ElementSnapshot, SnapshotStorage

logger = logging.getLogger('mops.self_healing')

_GET_CANDIDATES_JS = """
return (function(tag) {
    function getAttrs(node) {
        var attrs = {};
        for (var i = 0; i < node.attributes.length; i++) {
            attrs[node.attributes[i].name] = node.attributes[i].value;
        }
        return attrs;
    }
    function getSiblings(el) {
        var parent = el.parentElement;
        if (!parent) return [];
        var children = parent.children;
        var siblings = [];
        for (var i = 0; i < children.length && siblings.length < 5; i++) {
            if (children[i] !== el) {
                siblings.push({
                    tag: children[i].tagName.toLowerCase(),
                    text: (children[i].textContent || '').trim().substring(0, 50),
                    attrs: getAttrs(children[i])
                });
            }
        }
        return siblings;
    }
    var elements = document.getElementsByTagName(tag);
    var result = [];
    for (var i = 0; i < elements.length; i++) {
        var el = elements[i];
        var parent = el.parentElement;
        result.push({
            index: i,
            attrs: getAttrs(el),
            text: (el.textContent || '').trim().substring(0, 100),
            parentTag: parent ? parent.tagName.toLowerCase() : null,
            parentAttrs: parent ? getAttrs(parent) : {},
            siblings: getSiblings(el)
        });
    }
    return result;
})(arguments[0]);
"""


@dataclass
class ScoringWeights:
    """Tunable weights for the similarity scoring function.

    Each weight controls how much a signal contributes to the final 0-1 score.
    ``attribute`` is a per-attribute dict; the rest are scalar multipliers.
    """

    attribute: dict[str, float] = field(
        default_factory=lambda: {
            'id': 1.0,
            'name': 0.7,
            'placeholder': 0.5,
            'type': 0.4,
            'role': 0.3,
            'href': 0.3,
            'title': 0.2,
            'class': 0.15,
        }
    )
    text: float = 0.3
    parent: float = 0.2
    siblings: float = 0.15


@dataclass
class SuccessHealingResult:
    element_name: str
    original_locator: str
    healed_locator: str | None
    healed_locators_candidates: list[str]
    score: float
    page: str | None = None


@dataclass
class FailedHealingResult:
    element_name: str
    locator_key: str
    locator: str
    reason: str
    error: str | None = None


class Healer:
    """Orchestrates the self-healing process for a failed element lookup."""

    def __init__(
        self,
        storage: SnapshotStorage,
        score_threshold: float,
        scoring_weights: ScoringWeights | None = None,
        on_healing_success: Callable[[SuccessHealingResult], None] | None = None,
        on_healing_failure: Callable[[FailedHealingResult], None] | None = None,
    ) -> None:
        self._storage = storage
        self._score_threshold = score_threshold
        self._scoring_weights = scoring_weights or ScoringWeights()
        self._on_healing_success = on_healing_success
        self._on_healing_failure = on_healing_failure

    def _fail(
        self, reason: str, element_name: str, locator_key: str, locator: str, exc: BaseException | None = None
    ) -> None:
        """Fire failure callback and return None."""
        error: str | None = None
        if exc:
            error = exc.msg if isinstance(exc, WebDriverException) else str(exc)
        result = FailedHealingResult(
            element_name=element_name,
            locator_key=locator_key,
            locator=locator,
            reason=reason,
            error=error,
        )
        if self._on_healing_failure:
            self._on_healing_failure(result)

    def _succeed(self, result: SuccessHealingResult) -> SuccessHealingResult:
        """Fire success callback and return the result."""
        if self._on_healing_success:
            self._on_healing_success(result)
        return result

    def heal(self, element_name: str, locator_key: str, locator: str, driver: Any) -> SuccessHealingResult | None:
        """Try to find a healed locator for a failed element lookup.

        :param element_name: Human-readable element name for logging.
        :param locator_key: Storage key used to load the saved snapshot.
        :param locator: The original locator string (for the result record).
        :param driver: Selenium WebDriver instance.
        :return: :class:`SuccessHealingResult` if healed, ``None`` otherwise.
        """
        snapshot = self._storage.load(locator_key)

        if not snapshot:
            logger.info('Self-healing: no snapshot for "%s", skipping', element_name)
            return self._fail('no-snapshot', element_name, locator_key, locator)

        try:
            candidates_data: list[dict] = driver.execute_script(_GET_CANDIDATES_JS, snapshot.tag)
        except WebDriverException as exc:
            logger.info('Self-healing: failed to get candidates for "%s": %s', element_name, exc)
            return self._fail('candidates-script-error', element_name, locator_key, locator, exc=exc)

        if not candidates_data:
            return self._fail('no-candidates', element_name, locator_key, locator)

        best_score = 0.0
        best_index = -1

        for item in candidates_data:
            score = _score_similarity(item, snapshot, self._scoring_weights)
            if score > best_score:
                best_score = score
                best_index = item['index']

        if best_score < self._score_threshold or best_index < 0:
            logger.info(
                'Self-healing: best score %.2f below threshold %.2f for "%s"',
                best_score,
                self._score_threshold,
                element_name,
            )
            return self._fail('below-threshold', element_name, locator_key, locator)

        # Get the actual WebElement by index among elements of the same tag
        healed_locators: list[str] | None = None
        try:
            web_elements = driver.find_elements(By.TAG_NAME, snapshot.tag)
            if best_index >= len(web_elements):
                self._fail('index-out-of-bounds', element_name, locator_key, locator)
            else:
                healed_web_element = web_elements[best_index]
                healed_locators = generate_locator(healed_web_element, driver)
        except WebDriverException as exc:
            logger.info('Self-healing: failed to generate locator for "%s": %s', element_name, exc)
            self._fail('generate-locator-error', element_name, locator_key, locator, exc=exc)

        if healed_locators is None:
            return None

        result = SuccessHealingResult(
            element_name=element_name,
            original_locator=locator,
            healed_locator=None,
            healed_locators_candidates=healed_locators,
            score=best_score,
        )

        logger.info(
            'Self-healing: healed "%s"  %s -> %s  (score=%.2f)',
            element_name,
            locator,
            healed_locators,
            best_score,
        )

        return self._succeed(result)


def _score_similarity(
    candidate: dict[str, Any],
    snapshot: ElementSnapshot,
    weights: ScoringWeights | None = None,
) -> float:
    """Compute a 0-1 similarity score between a candidate DOM element and a saved snapshot."""
    w = weights or ScoringWeights()
    score = 0.0
    total_weight = 0.0

    # Attribute matching
    for attr, weight in w.attribute.items():
        snap_val = snapshot.attributes.get(attr)
        cand_val = candidate['attrs'].get(attr)

        if snap_val is None and cand_val is None:
            continue

        total_weight += weight

        if snap_val == cand_val:
            score += weight
        elif snap_val and cand_val:
            score += weight * _token_overlap(snap_val, cand_val)

    # Text similarity
    snap_text = snapshot.text
    cand_text = candidate.get('text', '')
    if snap_text:
        total_weight += w.text
        if snap_text == cand_text:
            score += w.text
        elif snap_text and cand_text:
            score += w.text * _text_similarity(snap_text, cand_text)

    # Parent tag match
    if snapshot.parent_tag and candidate.get('parentTag'):
        total_weight += w.parent
        if candidate['parentTag'] == snapshot.parent_tag:
            score += w.parent * 0.5
            parent_attr_score = _attrs_overlap(snapshot.parent_attributes, candidate.get('parentAttrs', {}))
            score += w.parent * 0.5 * parent_attr_score

    # Sibling similarity
    snap_siblings = snapshot.siblings
    cand_siblings = candidate.get('siblings', [])
    if snap_siblings:
        total_weight += w.siblings
        score += w.siblings * _siblings_similarity(snap_siblings, cand_siblings)

    if total_weight == 0:
        return 0.0

    return score / total_weight


def _token_overlap(a: str, b: str) -> float:
    """Jaccard token overlap for strings (e.g. CSS class lists)."""
    a_tokens = set(a.split())
    b_tokens = set(b.split())
    if not a_tokens or not b_tokens:
        return 0.0
    intersection = a_tokens & b_tokens
    union = a_tokens | b_tokens
    return len(intersection) / len(union)


def _text_similarity(a: str, b: str) -> float:
    a_lower = a.lower()
    b_lower = b.lower()
    if a_lower == b_lower:
        return 1.0
    if a_lower in b_lower or b_lower in a_lower:
        return 0.7
    return _token_overlap(a_lower, b_lower)


def _attrs_overlap(snap_attrs: dict[str, str], cand_attrs: dict[str, str]) -> float:
    """Average match score across attributes present in the snapshot."""
    if not snap_attrs:
        return 0.0
    matches = sum(1 for k, v in snap_attrs.items() if cand_attrs.get(k) == v)
    return matches / len(snap_attrs)


def _siblings_similarity(snap_siblings: list[dict], cand_siblings: list[dict]) -> float:
    """Compute 0-1 similarity between two sets of sibling elements."""
    if not snap_siblings:
        return 0.0

    total = 0.0
    for snap_sib in snap_siblings:
        best = 0.0
        for cand_sib in cand_siblings:
            tag_match = 1.0 if snap_sib.get('tag') == cand_sib.get('tag') else 0.0
            attr_score = _attrs_overlap(snap_sib.get('attrs', {}), cand_sib.get('attrs', {}))
            score = tag_match * 0.3 + attr_score * 0.7
            best = max(best, score)
        total += best

    return total / len(snap_siblings)

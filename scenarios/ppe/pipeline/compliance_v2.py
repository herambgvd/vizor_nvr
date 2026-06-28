"""Compliance rule engine v2 — ported from the AI-Powered PPE Detection System.

Rule per required item (AI-Powered): a worker is in VIOLATION for an item when the
detector saw the negative class (NO_X) OR did not see the positive class (X) on them.
That direct "no helmet box on this head → violation" is what gave the accurate results.

We keep vizor's per-track timers (missing-grace + alert cooldown) on top so a single
dropped frame doesn't fire a false alert and the same worker isn't re-alerted every
frame — that temporal stability is also what the live path needs. Confidence floors per
item still gate a weak positive box from counting as "worn".
"""
from __future__ import annotations

from dataclasses import dataclass, field

# canonical positive label per UI item.
ITEM_LABEL = {
    "helmet": "Hardhat",
    "vest": "Safety_Vest",
    "goggles": "Goggles",
    "boots": "Boots",
}
NEG_LABEL = {
    "Hardhat": "NO_Hardhat",
    "Safety_Vest": "NO_Safety_Vest",
    "Goggles": "NO_Goggles",
    "Boots": "NO_Boots",
}


@dataclass
class _ItemState:
    missing_since: float | None = None
    violation: bool = False
    last_alert_at: float = -1e12


@dataclass
class ComplianceEngineV2:
    """Direct has-positive / has-negative rule + missing-grace + cooldown.

    required: canonical positive labels to enforce, e.g. ["Hardhat", "Safety_Vest"].
    """
    required: list[str]
    missing_grace: float = 2.0
    cooldown: float = 30.0
    states: dict = field(default_factory=dict)        # track_id -> {label: _ItemState}
    last_seen: dict = field(default_factory=dict)

    def update(self, track_id: int, present: dict, negatives: dict, now: float,
               evaluable: set | None = None) -> list[tuple[str, str]]:
        """present/negatives: {label: Detection} for THIS person this frame.
        Returns [(event, canonical_label)] where event is PPE_MISSING.
        A required item fires when NO_X is seen OR X is absent — held for missing_grace
        and rate-limited by cooldown."""
        self.last_seen[track_id] = now
        st = self.states.setdefault(track_id, {})
        events: list[tuple[str, str]] = []
        for label in self.required:
            if evaluable is not None and label not in evaluable:
                continue
            has_pos = label in present
            has_neg = NEG_LABEL.get(label, "") in negatives
            item_state = st.setdefault(label, _ItemState())
            violated = has_neg or not has_pos
            if not violated:
                # worn now → clear timers, never alert
                item_state.missing_since = None
                item_state.violation = False
                continue
            if item_state.missing_since is None:
                item_state.missing_since = now
            if (now - item_state.missing_since) >= self.missing_grace and not item_state.violation:
                item_state.violation = True
                if now - item_state.last_alert_at >= self.cooldown:
                    events.append(("PPE_MISSING", label))
                    item_state.last_alert_at = now
        return events

    def is_compliant(self, track_id: int) -> bool:
        """True only when NO required item is currently in violation."""
        st = self.states.get(track_id, {})
        return all(not st.get(lbl, _ItemState()).violation for lbl in self.required)

    def purge(self, now: float, max_age: float = 10.0) -> None:
        for tid, last in list(self.last_seen.items()):
            if now - last > max_age:
                self.last_seen.pop(tid, None)
                self.states.pop(tid, None)

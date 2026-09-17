from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class Evidence:
    name: str
    passed: bool
    detail: str
    weight: float = 1.0
    index: int | None = None
    source_id: str | None = None


@dataclass(frozen=True)
class ResearchSignal:
    index: int
    direction: str
    evidence: tuple[Evidence, ...]

    @property
    def score(self) -> float:
        return sum(e.weight for e in self.evidence if e.passed)

    @property
    def possible_score(self) -> float:
        return sum(e.weight for e in self.evidence)

    @property
    def explanation(self) -> tuple[str, ...]:
        return tuple(f"{'PASS' if e.passed else 'FAIL'}: {e.name} — {e.detail}" for e in self.evidence)


EVIDENCE_ORDER = (
    "HTF context", "liquidity target", "liquidity event", "structural shift",
    "displacement", "PD array", "premium/discount", "candidate setup",
)


def build_candidate_signal(index: int, direction: str,
                           evidence: Iterable[Evidence]) -> ResearchSignal:
    """Build an explainable research candidate in canonical causal order."""
    rank = {name: position for position, name in enumerate(EVIDENCE_ORDER)}
    items = tuple(evidence)
    ordered = tuple(sorted(items, key=lambda item: (
        rank.get(item.name, len(rank)),
        item.index if item.index is not None else -1,
        item.source_id or "", item.name, item.detail, item.passed, item.weight,
    )))
    return ResearchSignal(index, direction, ordered)

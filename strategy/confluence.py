from dataclasses import dataclass


@dataclass(frozen=True)
class Evidence:
    name: str
    passed: bool
    detail: str
    weight: float = 1.0


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

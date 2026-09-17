from dataclasses import dataclass
from typing import Literal

Zone = Literal["premium", "equilibrium", "discount"]


@dataclass(frozen=True)
class DealingRange:
    low: float
    high: float

    def __post_init__(self):
        if self.high <= self.low:
            raise ValueError("high must be greater than low")

    @property
    def equilibrium(self) -> float:
        return (self.low + self.high) / 2

    def position(self, price: float, equilibrium_tolerance: float = 0.0) -> Zone:
        if equilibrium_tolerance < 0:
            raise ValueError("equilibrium_tolerance cannot be negative")
        if abs(price - self.equilibrium) <= equilibrium_tolerance:
            return "equilibrium"
        return "premium" if price > self.equilibrium else "discount"

    def retracement_price(self, fraction: float, from_high: bool = True) -> float:
        if not 0 <= fraction <= 1:
            raise ValueError("fraction must be in [0, 1]")
        span = self.high - self.low
        return self.high - span * fraction if from_high else self.low + span * fraction


def ote_band(rng: DealingRange, direction: str, lower_fraction: float = 0.62,
             upper_fraction: float = 0.79) -> tuple[float, float]:
    """Return a configurable retracement band as pure geometry."""
    if not 0 <= lower_fraction <= upper_fraction <= 1:
        raise ValueError("OTE fractions must satisfy 0 <= lower <= upper <= 1")
    if direction == "bullish":
        a = rng.retracement_price(upper_fraction, from_high=True)
        b = rng.retracement_price(lower_fraction, from_high=True)
    elif direction == "bearish":
        a = rng.retracement_price(lower_fraction, from_high=False)
        b = rng.retracement_price(upper_fraction, from_high=False)
    else:
        raise ValueError("direction must be bullish or bearish")
    return (min(a, b), max(a, b))

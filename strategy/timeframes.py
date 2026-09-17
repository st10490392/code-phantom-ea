from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")

@dataclass(frozen=True)
class ContextSeries(Generic[T]):
    """Timeframe-neutral container; labels are supplied, never fabricated."""
    candles: tuple[T, ...]
    timeframe: str | None = None
    timestamps: tuple[object, ...] | None = None

    def __post_init__(self):
        if self.timestamps is not None and len(self.timestamps) != len(self.candles):
            raise ValueError("timestamps and candles must have equal length")

@dataclass(frozen=True)
class MultiTimeframeContext(Generic[T]):
    execution: ContextSeries[T]
    higher_timeframes: tuple[ContextSeries[T], ...] = ()

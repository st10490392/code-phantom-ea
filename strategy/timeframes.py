from dataclasses import dataclass
from bisect import bisect_right
from typing import Generic, TypeVar

T = TypeVar("T")

@dataclass(frozen=True)
class ContextSeries(Generic[T]):
    """Timeframe-neutral container; labels are supplied, never fabricated."""
    candles: tuple[T, ...]
    timeframe: str | None = None
    timestamps: tuple[object, ...] | None = None

    def __post_init__(self):
        object.__setattr__(self, "candles", tuple(self.candles))
        if self.timestamps is not None:
            object.__setattr__(self, "timestamps", tuple(self.timestamps))
        if self.timestamps is not None and len(self.timestamps) != len(self.candles):
            raise ValueError("timestamps and candles must have equal length")
        if self.timestamps is not None:
            try:
                ordered = all(
                    left < right
                    for left, right in zip(self.timestamps, self.timestamps[1:])
                )
            except TypeError as error:
                raise ValueError("timestamps must be mutually comparable") from error
            if not ordered:
                raise ValueError("timestamps must be strictly increasing")

    def require_timestamps(self) -> tuple[object, ...]:
        if self.timestamps is None:
            raise ValueError("timestamps are required for multi-timeframe alignment")
        return self.timestamps

    def prefix(self, end_index: int) -> "ContextSeries[T]":
        """Return an immutable prefix ending at ``end_index`` (inclusive)."""
        if end_index < -1 or end_index >= len(self.candles):
            raise IndexError("end_index is outside the series")
        stop = end_index + 1
        timestamps = None if self.timestamps is None else self.timestamps[:stop]
        return ContextSeries(self.candles[:stop], self.timeframe, timestamps)


@dataclass(frozen=True)
class TimeframeAlignment:
    execution_index: int
    execution_timestamp: object
    higher_timeframe_index: int | None
    higher_timeframe_timestamp: object | None


def align_completed_candle(
    execution: ContextSeries[T], higher_timeframe: ContextSeries[T],
    execution_index: int,
) -> TimeframeAlignment:
    """Align to the latest HTF candle whose supplied completion time has passed.

    Timestamps are interpreted as candle completion timestamps. Equality means
    that the HTF candle is complete and visible. No duration is inferred from a
    timeframe label.
    """
    execution_times = execution.require_timestamps()
    higher_times = higher_timeframe.require_timestamps()
    if not 0 <= execution_index < len(execution.candles):
        raise IndexError("execution_index is outside the execution series")
    execution_time = execution_times[execution_index]
    try:
        higher_index = bisect_right(higher_times, execution_time) - 1
    except TypeError as error:
        raise ValueError("execution and higher-timeframe timestamps are not comparable") from error
    if higher_index < 0:
        return TimeframeAlignment(execution_index, execution_time, None, None)
    return TimeframeAlignment(
        execution_index, execution_time, higher_index, higher_times[higher_index]
    )

@dataclass(frozen=True)
class MultiTimeframeContext(Generic[T]):
    execution: ContextSeries[T]
    higher_timeframes: tuple[ContextSeries[T], ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "higher_timeframes", tuple(self.higher_timeframes))

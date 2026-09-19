"""Future outcomes computed only after causal observations have been frozen."""
from dataclasses import dataclass
from math import isfinite

from research.observer import utc_timestamp
from research.storage import fingerprint

LABEL_SCHEMA_VERSION = "research-labels/1"


@dataclass(frozen=True, slots=True)
class FutureLabel:
    schema_version: str
    instrument: str
    execution_timestamp: str
    execution_index: int
    observation_fingerprint: str
    horizon: int
    observed_bars: int
    horizon_complete: bool
    labelable: bool
    unlabelable_reason: str | None
    mfe: float | None
    mae: float | None
    mfe_r: float | None
    mae_r: float | None
    bars_to_1r: int | None
    bars_to_2r: int | None
    bars_to_invalidation: int | None
    one_r_before_invalidation: bool | None
    two_r_before_invalidation: bool | None
    outcome_1r: str
    outcome_2r: str
    ambiguity_1r: bool
    ambiguity_2r: bool
    same_candle_policy: str = "conservative"


def label_observation(observation, series, *, horizon=96):
    """Full-horizon excursions and first-touch races, strictly after entry.

    Excursions are descriptive full-window extremes, including bars after a
    target/stop; they are NOT realized P&L. Raw first-touch ages also span the
    full window. Independent 1R/stop and 2R/stop races use conservative ties.
    Missing future history is censored, never called horizon expiry.
    """
    if isinstance(horizon, bool) or not isinstance(horizon, int) or horizon < 1:
        raise ValueError("positive integer horizon required")
    i = observation.execution_index
    if not 0 <= i < len(series.candles):
        raise ValueError("observation outside source")
    candle = series.candles[i]
    if utc_timestamp(series.require_timestamps()[i]) != observation.execution_timestamp or (
            candle.open, candle.high, candle.low, candle.close) != (
            observation.open, observation.high, observation.low, observation.close):
        raise ValueError("observation/source mismatch")
    available = min(horizon, len(series.candles) - i - 1)
    common = (LABEL_SCHEMA_VERSION, observation.instrument, observation.execution_timestamp,
              i, fingerprint(observation), horizon, available, available == horizon)
    if not observation.levels_valid:
        return FutureLabel(*common, False, observation.levels_reason,
                           None, None, None, None, None, None, None, None, None,
                           "unlabelable", "unlabelable", False, False)
    entry, stop, risk = observation.entry, observation.invalidation, observation.risk_distance
    direction = observation.selected_direction
    if direction not in ("bullish", "bearish") or stop is None or risk is None or not all(
            isfinite(v) for v in (entry, stop, risk)) or risk <= 0 or risk != abs(entry - stop):
        raise ValueError("invalid observation levels")
    sign = 1 if direction == "bullish" else -1
    if sign * (entry - stop) <= 0:
        raise ValueError("invalid observation stop direction")
    mfe = mae = 0.0
    t1 = t2 = ts = None
    for age in range(1, available + 1):
        c = series.candles[i + age]
        if not all(isfinite(v) for v in (c.open, c.high, c.low, c.close)) or c.low > min(c.open, c.close) or c.high < max(c.open, c.close):
            raise ValueError("invalid future OHLC")
        favorable = c.high - entry if sign == 1 else entry - c.low
        adverse = entry - c.low if sign == 1 else c.high - entry
        mfe, mae = max(mfe, favorable), max(mae, adverse)
        if t1 is None and favorable >= risk:
            t1 = age
        if t2 is None and favorable >= 2 * risk:
            t2 = age
        if ts is None and adverse >= risk:
            ts = age

    def race(target):
        if ts is not None and (target is None or ts <= target):
            return False, "invalidation_first"
        if target is not None:
            return True, "target_first"
        return (False, "neither_within_horizon") if available == horizon else (None, "censored")

    before1, outcome1 = race(t1)
    before2, outcome2 = race(t2)
    return FutureLabel(*common, True, None,
                       mfe if available else None, mae if available else None,
                       mfe / risk if available else None, mae / risk if available else None,
                       t1, t2, ts, before1, before2, outcome1, outcome2,
                       ts is not None and t1 == ts, ts is not None and t2 == ts)

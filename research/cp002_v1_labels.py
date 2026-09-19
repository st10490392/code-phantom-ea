"""Separate offline CP-002 endpoint functions; synthetic verification only here.

No strategy/core module imports this module. No I/O or market-data execution.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from research.cp002 import identity
from research.cp002_v1 import Bar, Entry, validate_bar


@dataclass(frozen=True)
class Outcome:
    entry_id: str
    entry_fingerprint: str
    result: str
    observed_bars: int
    horizon_complete: bool
    ambiguous_stop_first: bool
    mfe: float | None
    mae: float | None
    first_outcome_start: object


def first_outcome_start(entry):
    if type(entry) is not Entry:
        raise TypeError("frozen CP-002 entry required")
    t = entry.candidate_available_at
    if entry.model == "A":
        return t
    # Strictly after, including confirmation exactly on an M15 boundary.
    seconds = int(t.timestamp())
    return datetime.fromtimestamp((seconds // 900 + 1) * 900, timezone.utc)


def label_entry(entry, bars, *, experiment_id):
    """96 full observed M15 bars; caller must bind the declared source identity.

    A confirmed normal closure contributes no invented bars. Missing coverage
    invalidates this full-window label; no missing-data loss is manufactured.
    Future information stays in this function's separate Outcome record.
    """
    start = first_outcome_start(entry)
    if experiment_id != entry.experiment_id:
        raise ValueError("experiment/source namespace mismatch")
    previous = None
    observed = 0
    result = None
    ambiguous = False
    mfe = mae = None
    next_start = start
    last_input = None
    for bar in bars:
        validate_bar(bar)
        if bar.stamp.timeframe != "M15": raise ValueError("standardized M15 outcomes only")
        if last_input is not None and bar.stamp.time <= last_input:
            raise ValueError("outcomes must be chronological and unique")
        last_input = bar.stamp.time
        if bar.start < start:
            continue  # explicitly excluded partial/entry intervals
        if previous is not None and bar.stamp.time <= previous.stamp.time:
            raise ValueError("outcomes must be chronological and unique")
        gap = bar.gap_before
        closure = (gap is not None and gap.kind == "MARKET_CLOSED"
                   and gap.start <= next_start and gap.end == bar.start
                   and (previous is None or gap.start == next_start))
        covered = (bar.complete and ((bar.start == next_start and gap is None) or closure)
                   and (previous is None or bar.stamp.index == previous.stamp.index + 1))
        if not covered:
            return Outcome(entry.id, identity(entry), "DATA_COVERAGE_FAILURE", observed,
                           False, False, None, None, start)
        observed += 1
        bullish = entry.path.mss.direction == "bullish"
        stop = bar.candle.low <= entry.stop if bullish else bar.candle.high >= entry.stop
        target = bar.candle.high >= entry.target if bullish else bar.candle.low <= entry.target
        if result is None and (stop or target):
            result = "STOP_FIRST" if stop else "TARGET_FIRST"
            ambiguous = bool(stop and target)
        favorable = (bar.candle.high - entry.reference_fill if bullish
                     else entry.reference_fill - bar.candle.low)
        adverse = (entry.reference_fill - bar.candle.low if bullish
                   else bar.candle.high - entry.reference_fill)
        mfe, mae = max(mfe or 0, favorable, 0), max(mae or 0, adverse, 0)
        previous, next_start = bar, bar.stamp.time
        if observed == 96: break
    complete = observed == 96
    return Outcome(entry.id, identity(entry), result or ("TIMEOUT" if complete else "CENSORED"),
                   observed, complete, ambiguous, mfe, mae, start)

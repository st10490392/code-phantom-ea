from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from strategy.structure import Candle, SwingPoint

Side = Literal["buy_side", "sell_side"]
LiquidityState = Literal["active", "touched", "wick_swept", "body_breached",
                         "reclaimed", "accepted_beyond", "structural_break"]

@dataclass(frozen=True)
class LiquidityPool:
    id: str
    side: Side
    level: float
    source_indices: tuple[int, ...]
    confirmed_at: int
    structure: str = "internal"
    state: Literal["active", "consumed"] = "active"

    @property
    def source_swing_index(self):
        return self.source_indices[0]

@dataclass(frozen=True)
class LiquidityEvent:
    index: int
    pool_id: str
    side: Side
    level: float
    state: LiquidityState
    close: float
    penetration_index: int | None = None
    confirmation_index: int | None = None
    direction: Literal["bullish", "bearish"] | None = None
    event_type: Literal["wick_sweep", "reclaim_sweep", "structural_break", "breach"] | None = None
    source_indices: tuple[int, ...] = ()
    pool_state: Literal["active", "consumed"] = "active"

def build_swing_pools(highs: list[SwingPoint], lows: list[SwingPoint],
                      tolerance: float = 0.0) -> list[LiquidityPool]:
    """Cluster equal highs/lows with an explicit absolute price tolerance."""
    if tolerance < 0:
        raise ValueError("tolerance cannot be negative")
    pools = []
    for swings, side in ((highs, "buy_side"), (lows, "sell_side")):
        groups = []
        for swing in sorted((s for s in swings if s.confirmed_at is not None),
                            key=lambda s: (s.confirmed_at, s.index)):
            decimal_price = Decimal(str(swing.price))
            decimal_tolerance = Decimal(str(tolerance))
            group = next((g for g in groups if abs(
                decimal_price
                - sum((Decimal(str(x.price)) for x in g), Decimal(0)) / len(g)
            ) <= decimal_tolerance), None)
            (group if group is not None else groups.append([swing]))
            if group is not None:
                group.append(swing)
        for n, group in enumerate(groups):
            pools.append(LiquidityPool(
                f"{side}:{n}:{group[0].index}", side,
                sum(s.price for s in group) / len(group),
                tuple(s.index for s in group),
                max(s.confirmed_at for s in group if s.confirmed_at is not None),
                "external" if any(s.structure == "external" for s in group) else "internal",
            ))
    return sorted(pools, key=lambda p: (p.confirmed_at, p.level, p.id))

def track_liquidity(candles: list[Candle], pools: list[LiquidityPool],
                    max_reclaim_window: int = 1) -> list[LiquidityEvent]:
    """Classify each pool once as wick sweep, reclaim sweep, or break.

    A source becomes usable on its exact ``confirmed_at`` completed-candle
    state. A close-through is pending until the explicit confirmation window
    expires; reclaim inside it consumes the pool as a reclaim sweep.
    """
    if max_reclaim_window < 0:
        raise ValueError("max_reclaim_window cannot be negative")
    events = []
    for pool in pools:
        if pool.state == "consumed":
            continue
        breached_at = None
        # Confirmation may equal the pivot index in manually constructed test
        # data.  A source candle can never consume its own liquidity.
        available_at = max(pool.confirmed_at, max(pool.source_indices) + 1)
        for i in range(available_at, len(candles)):
            candle = candles[i]
            beyond = candle.high > pool.level if pool.side == "buy_side" else candle.low < pool.level
            close_beyond = candle.close > pool.level if pool.side == "buy_side" else candle.close < pool.level
            close_back = candle.close < pool.level if pool.side == "buy_side" else candle.close > pool.level
            direction = "bearish" if pool.side == "buy_side" else "bullish"
            if breached_at is None:
                if not beyond:
                    continue
                if close_back:
                    events.append(LiquidityEvent(i, pool.id, pool.side, pool.level,
                        "wick_swept", candle.close, i, i, direction, "wick_sweep",
                        pool.source_indices, "consumed"))
                    break
                if not close_beyond:
                    events.append(LiquidityEvent(i, pool.id, pool.side, pool.level,
                        "touched", candle.close, i, None, direction, None,
                        pool.source_indices, "active"))
                    continue
                breached_at = i
                events.append(LiquidityEvent(i, pool.id, pool.side, pool.level,
                    "body_breached", candle.close, i, None, direction, "breach",
                    pool.source_indices, "active"))
                if max_reclaim_window == 0:
                    events.append(LiquidityEvent(i, pool.id, pool.side, pool.level,
                        "accepted_beyond", candle.close, i, i,
                        "bullish" if pool.side == "buy_side" else "bearish",
                        "structural_break", pool.source_indices, "consumed"))
                    break
                continue
            if i <= breached_at + max_reclaim_window and close_back:
                events.append(LiquidityEvent(i, pool.id, pool.side, pool.level,
                    "reclaimed", candle.close, breached_at, i, direction,
                    "reclaim_sweep", pool.source_indices, "consumed"))
                break
            if i >= breached_at + max_reclaim_window:
                events.append(LiquidityEvent(i, pool.id, pool.side, pool.level,
                    "accepted_beyond", candle.close, breached_at, i,
                    "bullish" if pool.side == "buy_side" else "bearish",
                    "structural_break", pool.source_indices, "consumed"))
                break
    # Python's sort is stable, so events at the same candle/pool retain their
    # causal insertion order (breach before terminal classification).
    return sorted(events, key=lambda e: (e.index, e.pool_id))

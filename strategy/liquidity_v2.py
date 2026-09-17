from dataclasses import dataclass
from typing import Literal

from strategy.structure import Candle, SwingPoint

Side = Literal["buy_side", "sell_side"]
LiquidityState = Literal[
    "active", "touched", "wick_swept", "body_breached",
    "reclaimed", "accepted_beyond"
]


@dataclass(frozen=True)
class LiquidityPool:
    id: str
    side: Side
    level: float
    source_indices: tuple[int, ...]
    confirmed_at: int
    structure: str = "internal"


@dataclass(frozen=True)
class LiquidityEvent:
    index: int
    pool_id: str
    side: Side
    level: float
    state: LiquidityState
    close: float


def build_swing_pools(
    highs: list[SwingPoint],
    lows: list[SwingPoint],
    tolerance: float = 0.0,
) -> list[LiquidityPool]:
    """Create confirmed liquidity pools; nearby equal levels may be clustered."""
    if tolerance < 0:
        raise ValueError("tolerance cannot be negative")

    pools: list[LiquidityPool] = []

    def cluster(swings: list[SwingPoint], side: Side):
        confirmed = sorted(
            (s for s in swings if s.confirmed_at is not None),
            key=lambda s: (s.confirmed_at, s.index),
        )
        groups: list[list[SwingPoint]] = []
        for swing in confirmed:
            match = next(
                (g for g in groups if abs(swing.price - sum(x.price for x in g) / len(g)) <= tolerance),
                None,
            )
            if match is None:
                groups.append([swing])
            else:
                match.append(swing)

        for n, group in enumerate(groups):
            level = sum(s.price for s in group) / len(group)
            pools.append(
                LiquidityPool(
                    id=f"{side}:{n}:{group[0].index}",
                    side=side,
                    level=level,
                    source_indices=tuple(s.index for s in group),
                    confirmed_at=max(s.confirmed_at for s in group if s.confirmed_at is not None),
                    structure="external" if any(s.structure == "external" for s in group) else "internal",
                )
            )

    cluster(highs, "buy_side")
    cluster(lows, "sell_side")
    return sorted(pools, key=lambda p: (p.confirmed_at, p.level))


def track_liquidity(candles: list[Candle], pools: list[LiquidityPool]) -> list[LiquidityEvent]:
    """Track touch, wick sweep, body breach, reclaim and acceptance.

    A body close beyond a pool is not immediately called a sweep. If a later
    candle reclaims the level it becomes a reclaimed event; otherwise a second
    close holding beyond it records acceptance/breakout behaviour.
    """
    events: list[LiquidityEvent] = []

    for pool in pools:
        breached_at: int | None = None
        for i in range(pool.confirmed_at, len(candles)):
            c = candles[i]
            if pool.side == "buy_side":
                traded_beyond = c.high > pool.level
                closed_beyond = c.close > pool.level
                reclaimed = c.close < pool.level
            else:
                traded_beyond = c.low < pool.level
                closed_beyond = c.close < pool.level
                reclaimed = c.close > pool.level

            if breached_at is not None:
                if reclaimed:
                    events.append(LiquidityEvent(i, pool.id, pool.side, pool.level, "reclaimed", c.close))
                    break
                if closed_beyond and i > breached_at:
                    events.append(LiquidityEvent(i, pool.id, pool.side, pool.level, "accepted_beyond", c.close))
                    break
                continue

            if not traded_beyond:
                continue

            if closed_beyond:
                events.append(LiquidityEvent(i, pool.id, pool.side, pool.level, "body_breached", c.close))
                breached_at = i
            else:
                events.append(LiquidityEvent(i, pool.id, pool.side, pool.level, "wick_swept", c.close))
                break

    return events

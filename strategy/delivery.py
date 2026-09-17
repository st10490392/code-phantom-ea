from dataclasses import dataclass
from typing import Literal

from strategy.structure import Candle

Direction = Literal["bullish", "bearish"]


@dataclass(frozen=True)
class DeliveryLeg:
    start: int
    end: int
    direction: Direction
    start_price: float
    end_price: float
    range: float
    body_sum: float
    efficiency: float
    candle_count: int = 0
    net_movement: float = 0.0
    average_body: float = 0.0
    average_range: float = 0.0
    displacement_indices: tuple[int, ...] = ()
    origin_swing_index: int | None = None
    terminal_swing_index: int | None = None


@dataclass(frozen=True)
class CISDEvent:
    index: int
    direction: Direction
    reference_open: float
    run_start: int
    run_end: int


def candle_direction(candle: Candle) -> Direction | None:
    if candle.close > candle.open:
        return "bullish"
    if candle.close < candle.open:
        return "bearish"
    return None


def detect_delivery_legs(
    candles: list[Candle], min_candles: int = 2, *,
    displacement_lookback: int = 3,
    displacement_range_multiple: float = 1.5,
    displacement_body_ratio: float = 0.6,
    swings=(),
) -> list[DeliveryLeg]:
    """Group consecutive directional closes into price-delivery legs.

    This deliberately does not require a fixed fractal pivot. A four/five-candle
    expansion can therefore be represented as one leg even before a later
    symmetric swing-window would be available.
    """
    if min_candles < 1:
        raise ValueError("min_candles must be at least 1")

    from strategy.fvg import detect_displacement
    displacements = detect_displacement(
        candles, displacement_lookback, displacement_range_multiple,
        displacement_body_ratio,
    )

    legs: list[DeliveryLeg] = []
    start = 0

    while start < len(candles):
        direction = candle_direction(candles[start])
        if direction is None:
            start += 1
            continue

        end = start
        while end + 1 < len(candles) and candle_direction(candles[end + 1]) == direction:
            end += 1

        count = end - start + 1
        if count >= min_candles:
            segment = candles[start:end + 1]
            high = max(c.high for c in segment)
            low = min(c.low for c in segment)
            total_range = high - low
            body_sum = sum(abs(c.close - c.open) for c in segment)
            net = abs(segment[-1].close - segment[0].open)
            efficiency = net / body_sum if body_sum else 0.0
            ranges = [c.high - c.low for c in segment]
            legs.append(
                DeliveryLeg(
                    start=start,
                    end=end,
                    direction=direction,
                    start_price=segment[0].open,
                    end_price=segment[-1].close,
                    range=total_range,
                    body_sum=body_sum,
                    efficiency=efficiency,
                    candle_count=count,
                    net_movement=net,
                    average_body=body_sum / count,
                    average_range=sum(ranges) / count,
                    displacement_indices=tuple(
                        d.index for d in displacements if start <= d.index <= end
                    ),
                    origin_swing_index=next((s.index for s in swings if s.index == start), None),
                    terminal_swing_index=next((s.index for s in swings if s.index == end), None),
                )
            )
        start = end + 1

    return legs


def detect_cisd(candles: list[Candle], min_run: int = 1) -> list[CISDEvent]:
    """Detect close-confirmed Change in State of Delivery.

    Bullish: after a run of bearish candles, a later close reclaims the opening
    price of the first candle in that final bearish run.
    Bearish: inverse logic.
    """
    if min_run < 1:
        raise ValueError("min_run must be at least 1")

    events: list[CISDEvent] = []
    legs = detect_delivery_legs(candles, min_candles=min_run)

    for leg in legs:
        reference = candles[leg.start].open
        target = "bullish" if leg.direction == "bearish" else "bearish"
        for index in range(leg.end + 1, len(candles)):
            close = candles[index].close
            crossed = close > reference if target == "bullish" else close < reference
            if crossed:
                events.append(CISDEvent(index, target, reference, leg.start, leg.end))
                break

    return events

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


def detect_delivery_legs(candles: list[Candle], min_candles: int = 2) -> list[DeliveryLeg]:
    """Group consecutive directional closes into price-delivery legs.

    This deliberately does not require a fixed fractal pivot. A four/five-candle
    expansion can therefore be represented as one leg even before a later
    symmetric swing-window would be available.
    """
    if min_candles < 1:
        raise ValueError("min_candles must be at least 1")

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

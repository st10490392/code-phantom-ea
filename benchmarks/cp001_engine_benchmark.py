"""Non-market deterministic benchmark for the CP-001 engine refactor."""

import argparse
import random
import time

from strategy.engine import EngineConfig, SequentialResearchEngine
from strategy.optimized_engine import OptimizedSequentialResearchEngine
from strategy.structure import Candle
from strategy.timeframes import ContextSeries


def benchmark_series(count: int) -> ContextSeries:
    rng = random.Random(8675309)
    price = 100.0
    candles = []
    for index in range(count):
        opening = price
        change = 0.0 if index % 29 == 0 else rng.uniform(-2.5, 2.5)
        if index % 37 == 0:
            change *= 4
        close = opening + change
        high_wick = 0.0 if index % 31 == 0 else rng.uniform(0, 1.2)
        low_wick = 0.0 if index % 31 == 0 else rng.uniform(0, 1.2)
        candles.append(Candle(opening, max(opening, close) + high_wick,
                              min(opening, close) - low_wick, close))
        price = close
    return ContextSeries(tuple(candles), "deterministic-non-market-benchmark")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-max", type=int, default=400)
    args = parser.parse_args()
    config = EngineConfig(liquidity_tolerance=0.05)
    previous = {"reference": None, "optimized": None}
    for count in (100, 200, 400, 800, 1600, 3200):
        series = benchmark_series(count)
        results = {}
        oracle = None
        classes = [("optimized", OptimizedSequentialResearchEngine)]
        if count <= args.reference_max:
            classes.insert(0, ("reference", SequentialResearchEngine))
        for name, engine_type in classes:
            started = time.perf_counter()
            snapshots = engine_type(series, config=config).run()
            results[name] = time.perf_counter() - started
            if name == "reference":
                oracle = snapshots
            elif oracle is not None:
                assert snapshots == oracle
        fields = [f"n={count}"]
        for name in ("reference", "optimized"):
            if name not in results:
                continue
            growth = (None if previous[name] is None else
                      results[name] / previous[name])
            fields.extend((f"{name}={results[name]:.6f}s",
                           f"{name}_growth={growth if growth is not None else 'n/a'}"))
            previous[name] = results[name]
        if "reference" in results:
            fields.append(f"speedup={results['reference'] / results['optimized']:.3f}x")
        print(" ".join(fields), flush=True)


if __name__ == "__main__":
    main()

"""Non-market Revision 1 versus Revision 2 CP-001 engine benchmark."""

import time

from benchmarks.cp001_engine_benchmark import benchmark_series
from strategy.engine import EngineConfig
from strategy.optimized_engine import OptimizedSequentialResearchEngine
from strategy.optimized_engine_v2 import OptimizedSequentialResearchEngineV2


def main() -> None:
    config = EngineConfig()
    previous = {"revision_1": None, "revision_2": None}
    for count in (1000, 2000, 4000, 8000, 16000):
        series = benchmark_series(count)
        results = {}
        snapshot_results = {}
        classes = [("revision_2", OptimizedSequentialResearchEngineV2)]
        if count <= 4000:
            classes.insert(0, ("revision_1", OptimizedSequentialResearchEngine))
        for name, engine_type in classes:
            started = time.perf_counter()
            snapshots = engine_type(series, config=config).run()
            results[name] = time.perf_counter() - started
            snapshot_results[name] = snapshots
        if "revision_1" in snapshot_results:
            assert snapshot_results["revision_1"] == snapshot_results["revision_2"]
        fields = [f"n={count}"]
        for name in ("revision_1", "revision_2"):
            if name not in results:
                continue
            growth = (None if previous[name] is None else
                      results[name] / previous[name])
            fields.extend((f"{name}={results[name]:.6f}s",
                           f"{name}_growth={growth if growth is not None else 'n/a'}"))
            previous[name] = results[name]
        if "revision_1" in results:
            fields.append(
                f"speedup={results['revision_1'] / results['revision_2']:.3f}x")
        print(" ".join(fields), flush=True)


if __name__ == "__main__":
    main()

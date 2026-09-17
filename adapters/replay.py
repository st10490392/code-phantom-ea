"""Offline replay contracts and implementations; no network connectivity."""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from backtest.experiment import ExperimentConfig, ExperimentRunner
from data.historical import HistoricalCandle, HistoricalDataset
from strategy.confluence import ResearchSignal
from strategy.engine import EngineSnapshot

ADAPTER_STATE_VERSION = "1.0"


class CompletedCandleSource(Protocol):
    def next_completed_candle(self) -> HistoricalCandle | None: ...


class TimeSource(Protocol):
    def now(self) -> datetime: ...


class ObservationalSignalSink(Protocol):
    def accept(self, signal: ResearchSignal, timestamp: datetime) -> None: ...


class EventContextSource(Protocol):
    def visible_at(self, timestamp: datetime) -> tuple[Any, ...]: ...


class StatePersistence(Protocol):
    def save(self, state: dict[str, Any]) -> None: ...
    def load(self) -> dict[str, Any] | None: ...


class HealthReporter(Protocol):
    def report(self, status: str, detail: str) -> None: ...


class InMemoryCompletedCandleSource:
    def __init__(self, candles):
        self._candles, self._index = tuple(candles), 0

    def next_completed_candle(self):
        if self._index == len(self._candles):
            return None
        value = self._candles[self._index]
        self._index += 1
        return value


@dataclass(frozen=True)
class OfflineClock:
    current: datetime

    def __post_init__(self):
        if self.current.tzinfo is None or self.current.utcoffset() is None:
            raise ValueError("offline clock must be timezone-aware")
        object.__setattr__(self, "current", self.current.astimezone(UTC))

    def now(self):
        return self.current


class CollectingSignalSink:
    def __init__(self):
        self._items = []

    @property
    def items(self):
        return tuple(self._items)

    def accept(self, signal, timestamp):
        self._items.append((signal, timestamp.astimezone(UTC)))


class MonitoringHealthReporter:
    def __init__(self):
        self._items = []

    @property
    def items(self):
        return tuple(self._items)

    def report(self, status, detail):
        self._items.append((status, detail))


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class LocalJsonStateStore:
    def __init__(self, path):
        self.path = Path(path)

    def save(self, state):
        payload = {"schema_version": ADAPTER_STATE_VERSION, "state": state}
        envelope = {"checksum": hashlib.sha256(_json(payload).encode()).hexdigest(),
                    "payload": payload}
        self.path.write_text(_json(envelope) + "\n", encoding="utf-8")

    def load(self):
        if not self.path.exists():
            return None
        try:
            envelope = json.loads(self.path.read_text(encoding="utf-8"))
            if set(envelope) != {"checksum", "payload"}:
                raise ValueError
            payload = envelope["payload"]
            if set(payload) != {"schema_version", "state"} \
                    or payload["schema_version"] != ADAPTER_STATE_VERSION \
                    or not isinstance(payload["state"], dict) \
                    or hashlib.sha256(_json(payload).encode()).hexdigest() != envelope["checksum"]:
                raise ValueError
            return payload["state"]
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise ValueError("replay state is corrupt or has an incompatible schema") from error


@dataclass(frozen=True)
class ReplayLogRecord:
    timestamp: datetime
    event: str
    detail: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ReplayResult:
    snapshots: tuple[EngineSnapshot, ...]
    signals: tuple[ResearchSignal, ...]
    records: tuple[ReplayLogRecord, ...]
    accepted_candles: tuple[HistoricalCandle, ...]


def _candle_dict(item):
    return {"timestamp": item.timestamp.isoformat().replace("+00:00", "Z"),
            "open": item.open, "high": item.high, "low": item.low,
            "close": item.close, "volume": item.volume}


def _candle_load(value):
    if not isinstance(value, dict) or set(value) != {
            "timestamp", "open", "high", "low", "close", "volume"}:
        raise ValueError("persisted candle fields are malformed")
    try:
        stamp = datetime.fromisoformat(value["timestamp"].replace("Z", "+00:00"))
        return HistoricalCandle(stamp, value["open"], value["high"], value["low"],
                                value["close"], value["volume"])
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("persisted candle is malformed") from error


class ReplayAdapter:
    """Feed only accepted historical prefixes through the research runner."""

    def __init__(self, source, configuration, *, signal_sink=None,
                 persistence=None, health=None, resume=False):
        self.source, self.configuration = source, configuration
        self.signal_sink, self.persistence, self.health = signal_sink, persistence, health
        self._accepted = []
        if resume:
            if persistence is None:
                raise ValueError("resume requires state persistence")
            state = persistence.load()
            if state is not None:
                if set(state) != {"dataset_identifier", "candles"} \
                        or state["dataset_identifier"] != configuration.dataset_identifier \
                        or not isinstance(state["candles"], list):
                    raise ValueError("persisted replay state does not match configuration")
                self._accepted = [_candle_load(item) for item in state["candles"]]
                if self._accepted:
                    HistoricalDataset(tuple(self._accepted), configuration.dataset_identifier)

    @staticmethod
    def _record(timestamp, event, **detail):
        return ReplayLogRecord(timestamp, event,
                               tuple(sorted((key, str(value)) for key, value in detail.items())))

    def run(self):
        snapshots, signals, records = [], [], []
        while (candle := self.source.next_completed_candle()) is not None:
            if not isinstance(candle, HistoricalCandle):
                raise TypeError("completed candle source returned an invalid candle")
            if self._accepted and candle.timestamp <= self._accepted[-1].timestamp:
                raise ValueError("completed candles must have strictly increasing timestamps")
            self._accepted.append(candle)
            dataset = HistoricalDataset(tuple(self._accepted),
                                        self.configuration.dataset_identifier)
            snapshot = ExperimentRunner(dataset, self.configuration).run().snapshots[-1]
            snapshots.append(snapshot)
            records.append(self._record(candle.timestamp, "candle_accepted",
                                        index=len(self._accepted) - 1))
            records.append(self._record(candle.timestamp, "context_updated",
                                        htf_bias=snapshot.htf_context.bias))
            if snapshot.signal:
                signals.append(snapshot.signal)
                records.append(self._record(candle.timestamp, "candidate_generated",
                                            direction=snapshot.signal.direction,
                                            index=snapshot.signal.index))
                if self.signal_sink:
                    self.signal_sink.accept(snapshot.signal, candle.timestamp)
            else:
                failed = tuple(item.name for item in snapshot.evidence if not item.satisfied)
                records.append(self._record(candle.timestamp, "candidate_rejected",
                                            reasons=",".join(failed) or "no candidate"))
            if self.persistence:
                self.persistence.save({"dataset_identifier": self.configuration.dataset_identifier,
                                       "candles": [_candle_dict(x) for x in self._accepted]})
        if self.health:
            self.health.report("healthy", f"accepted={len(self._accepted)}")
        return ReplayResult(tuple(snapshots), tuple(signals), tuple(records),
                            tuple(self._accepted))

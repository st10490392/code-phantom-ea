"""Offline session and point-in-time historical event context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from strategy.confluence import ResearchSignal


def _aware(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True)
class SessionWindow:
    name: str
    timezone: str
    start: time
    end: time

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("session name cannot be empty")
        if self.start.tzinfo is not None or self.end.tzinfo is not None:
            raise ValueError("session wall-clock boundaries must be naive times")
        if self.start == self.end:
            raise ValueError("session start and end cannot be equal")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as error:
            raise ValueError(f"unknown session timezone {self.timezone!r}") from error

    def contains(self, timestamp: datetime) -> bool:
        local = _aware(timestamp, "timestamp").astimezone(ZoneInfo(self.timezone)).time()
        if self.start < self.end:
            return self.start <= local < self.end
        return local >= self.start or local < self.end


@dataclass(frozen=True)
class HistoricalEventVersion:
    event_timestamp: datetime
    available_at: datetime
    event_identifier: str
    category: str
    currency_or_region: str
    importance: str | None = None
    actual: str | None = None
    forecast: str | None = None
    previous: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_timestamp",
                           _aware(self.event_timestamp, "event_timestamp"))
        object.__setattr__(self, "available_at", _aware(self.available_at, "available_at"))
        if not self.event_identifier:
            raise ValueError("event_identifier cannot be empty")
        if not self.category:
            raise ValueError("event category cannot be empty")


class HistoricalEventStore:
    """Immutable version store queried using historical availability time."""

    def __init__(self, versions: tuple[HistoricalEventVersion, ...] |
                 list[HistoricalEventVersion]):
        copied = tuple(versions)
        keys = [(item.event_identifier, item.available_at) for item in copied]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate event version availability")
        self._versions = tuple(sorted(copied, key=lambda item: (
            item.available_at, item.event_timestamp, item.event_identifier)))

    @property
    def versions(self) -> tuple[HistoricalEventVersion, ...]:
        return self._versions

    def visible_at(self, timestamp: datetime) -> tuple[HistoricalEventVersion, ...]:
        point = _aware(timestamp, "timestamp")
        latest: dict[str, HistoricalEventVersion] = {}
        for item in self._versions:
            if item.available_at > point:
                break
            latest[item.event_identifier] = item
        return tuple(sorted(latest.values(), key=lambda item: (
            item.event_timestamp, item.event_identifier)))


@dataclass(frozen=True)
class EventExclusion:
    before: timedelta = timedelta(0)
    after: timedelta = timedelta(0)
    categories: tuple[str, ...] = ()
    currencies_or_regions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.before < timedelta(0) or self.after < timedelta(0):
            raise ValueError("event exclusion durations cannot be negative")
        object.__setattr__(self, "categories", tuple(self.categories))
        object.__setattr__(self, "currencies_or_regions",
                           tuple(self.currencies_or_regions))

    def matches(self, event: HistoricalEventVersion) -> bool:
        return ((not self.categories or event.category in self.categories)
                and (not self.currencies_or_regions
                     or event.currency_or_region in self.currencies_or_regions))


@dataclass(frozen=True)
class SignalTemporalContext:
    signal: ResearchSignal
    timestamp: datetime
    sessions: tuple[str, ...]
    visible_events: tuple[HistoricalEventVersion, ...]
    exclusion_event_identifiers: tuple[str, ...]
    eligible: bool
    rejection_reasons: tuple[str, ...]


def contextualize_signal(signal: ResearchSignal, timestamp: datetime, *,
                         sessions: tuple[SessionWindow, ...] | list[SessionWindow] = (),
                         required_sessions: tuple[str, ...] | list[str] = (),
                         event_store: HistoricalEventStore | None = None,
                         exclusion: EventExclusion | None = None) -> SignalTemporalContext:
    """Annotate/filter one observation without mutating the research signal."""
    point = _aware(timestamp, "timestamp")
    session_tuple = tuple(sessions)
    names = [item.name for item in session_tuple]
    if len(set(names)) != len(names):
        raise ValueError("session names must be unique")
    required = tuple(required_sessions)
    unknown = sorted(set(required) - set(names))
    if unknown:
        raise ValueError(f"unknown required sessions: {', '.join(unknown)}")
    active = tuple(item.name for item in session_tuple if item.contains(point))
    visible = () if event_store is None else event_store.visible_at(point)
    excluded = ()
    if exclusion is not None:
        excluded = tuple(item.event_identifier for item in visible
                         if exclusion.matches(item)
                         and item.event_timestamp - exclusion.before <= point
                         <= item.event_timestamp + exclusion.after)
    reasons = []
    if required and not any(name in active for name in required):
        reasons.append("outside required session")
    if excluded:
        reasons.append("inside historical event exclusion")
    return SignalTemporalContext(signal, point, active, visible, excluded,
                                 not reasons, tuple(reasons))

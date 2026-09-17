from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, time, timedelta

import pytest

from strategy.confluence import Evidence, ResearchSignal
from strategy.temporal_context import (EventExclusion, HistoricalEventStore,
                                       HistoricalEventVersion, SessionWindow,
                                       contextualize_signal)


def signal():
    return ResearchSignal(4, "bullish", (Evidence("candidate", True, "fixture"),))


def event(*, available, actual=None, previous=None):
    return HistoricalEventVersion(
        datetime(2026, 3, 10, 14, 0, tzinfo=UTC), available, "us-cpi", "inflation",
        "USD", "high", actual, "2.5", previous)


def test_session_exact_boundaries_and_midnight_crossing():
    london = SessionWindow("London", "UTC", time(8), time(16))
    assert london.contains(datetime(2026, 1, 1, 8, tzinfo=UTC))
    assert london.contains(datetime(2026, 1, 1, 15, 59, tzinfo=UTC))
    assert not london.contains(datetime(2026, 1, 1, 16, tzinfo=UTC))
    asia = SessionWindow("Asia", "UTC", time(22), time(6))
    assert asia.contains(datetime(2026, 1, 1, 23, tzinfo=UTC))
    assert asia.contains(datetime(2026, 1, 2, 5, 59, tzinfo=UTC))
    assert not asia.contains(datetime(2026, 1, 2, 6, tzinfo=UTC))


def test_session_dst_uses_named_timezone_at_each_timestamp():
    ny = SessionWindow("New York", "America/New_York", time(9, 30), time(16))
    assert ny.contains(datetime(2026, 1, 15, 14, 30, tzinfo=UTC))  # EST
    assert ny.contains(datetime(2026, 7, 15, 13, 30, tzinfo=UTC))  # EDT
    assert not ny.contains(datetime(2026, 7, 15, 20, 0, tzinfo=UTC))


def test_future_release_and_revision_are_invisible_until_exact_availability():
    scheduled = event(available=datetime(2026, 3, 1, tzinfo=UTC))
    released = event(available=datetime(2026, 3, 10, 14, tzinfo=UTC), actual="2.7")
    revised = event(available=datetime(2026, 4, 1, tzinfo=UTC), actual="2.6",
                    previous="2.7")
    store = HistoricalEventStore((revised, released, scheduled))
    before = store.visible_at(datetime(2026, 3, 10, 13, 59, tzinfo=UTC))[0]
    assert before.actual is None
    assert store.visible_at(datetime(2026, 3, 10, 14, tzinfo=UTC))[0].actual == "2.7"
    assert store.visible_at(datetime(2026, 3, 31, tzinfo=UTC))[0].actual == "2.7"
    assert store.visible_at(datetime(2026, 4, 1, tzinfo=UTC))[0].actual == "2.6"


def test_before_after_event_exclusion_requires_point_in_time_visibility():
    scheduled = event(available=datetime(2026, 3, 1, tzinfo=UTC))
    store = HistoricalEventStore((scheduled,))
    exclusion = EventExclusion(timedelta(minutes=15), timedelta(minutes=10))
    assert contextualize_signal(signal(), datetime(2026, 3, 10, 13, 45, tzinfo=UTC),
                                event_store=store, exclusion=exclusion).eligible is False
    assert contextualize_signal(signal(), datetime(2026, 3, 10, 14, 10, tzinfo=UTC),
                                event_store=store, exclusion=exclusion).eligible is False
    assert contextualize_signal(signal(), datetime(2026, 3, 10, 14, 11, tzinfo=UTC),
                                event_store=store, exclusion=exclusion).eligible is True
    unknown_store = HistoricalEventStore((event(available=datetime(2026, 3, 10, 14,
                                                                    tzinfo=UTC)),))
    assert contextualize_signal(signal(), datetime(2026, 3, 10, 13, 50, tzinfo=UTC),
                                event_store=unknown_store, exclusion=exclusion).eligible


def test_session_requirement_annotation_filtering_and_immutability():
    sessions = (SessionWindow("London", "Europe/London", time(8), time(16)),)
    inside = contextualize_signal(signal(), datetime(2026, 6, 1, 8, tzinfo=UTC),
                                  sessions=sessions, required_sessions=("London",))
    assert inside.eligible and inside.sessions == ("London",)
    outside = contextualize_signal(signal(), datetime(2026, 6, 1, 16, tzinfo=UTC),
                                   sessions=sessions, required_sessions=("London",))
    assert not outside.eligible
    with pytest.raises(FrozenInstanceError):
        inside.eligible = False
    with pytest.raises(ValueError, match="unknown"):
        contextualize_signal(signal(), datetime.now(UTC), sessions=sessions,
                             required_sessions=("Asia",))


def test_prefix_invariance_and_caller_collection_mutation():
    versions = [event(available=datetime(2026, 3, 1, tzinfo=UTC))]
    store = HistoricalEventStore(versions)
    point = datetime(2026, 3, 10, 13, 50, tzinfo=UTC)
    original = contextualize_signal(signal(), point, event_store=store,
                                    exclusion=EventExclusion(timedelta(minutes=15)))
    versions.append(event(available=datetime(2026, 4, 1, tzinfo=UTC), actual="revised"))
    assert contextualize_signal(signal(), point, event_store=store,
                                exclusion=EventExclusion(timedelta(minutes=15))) == original
    extended = HistoricalEventStore(tuple(versions))
    assert contextualize_signal(signal(), point, event_store=extended,
                                exclusion=EventExclusion(timedelta(minutes=15))) == original


def test_invalid_temporal_configuration_is_rejected():
    with pytest.raises(ValueError):
        SessionWindow("bad", "UTC", time(1), time(1))
    with pytest.raises(ValueError):
        SessionWindow("bad", "Not/AZone", time(1), time(2))
    with pytest.raises(ValueError):
        EventExclusion(timedelta(seconds=-1))
    item = event(available=datetime(2026, 3, 1, tzinfo=UTC))
    with pytest.raises(ValueError, match="duplicate"):
        HistoricalEventStore((item, item))

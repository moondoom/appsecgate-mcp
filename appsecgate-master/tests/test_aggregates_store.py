"""AggregateStore: rebuild из events, get/list, изоляция по (project, fp)."""

from __future__ import annotations

from helpers import BASE_AT, FP, make_event, prime, shift_at

from appsecgate_master.storage import AggregateStore, MasterEventStore


async def test_rebuild_materializes_aggregates(
    events_store: MasterEventStore, aggregates_store: AggregateStore
):
    events = prime("REOPENED") + [make_event("verify_fixed", at=shift_at(BASE_AT, 10))]
    await events_store.ingest(events)
    assert await aggregates_store.rebuild() == 1
    state = await aggregates_store.get_state("proj", FP)
    assert state is not None
    assert state.status == "FIXED"
    assert state.verified_status == "fixed"
    assert state.scan_count == 2  # discovered + reopened


async def test_rebuild_counts_all_projects_and_fps(
    events_store: MasterEventStore, aggregates_store: AggregateStore
):
    await events_store.ingest(
        [
            make_event("discovered", project_key="p1", fp="fp-1"),
            make_event("discovered", project_key="p1", fp="fp-2"),
            make_event("discovered", project_key="p2", fp="fp-1"),
        ]
    )
    assert await aggregates_store.rebuild() == 3
    assert (await aggregates_store.get_state("p1", "fp-1")).status == "SHOWN"
    assert (await aggregates_store.get_state("p2", "fp-1")).status == "SHOWN"


async def test_rebuild_ignores_config_policy(
    events_store: MasterEventStore, aggregates_store: AggregateStore
):
    await events_store.ingest([make_event("discovered"), make_event("config_policy", fp=None)])
    assert await aggregates_store.rebuild() == 1  # config_policy без fp не считается
    state = await aggregates_store.get_state("proj", FP)
    assert state is not None
    assert state.status == "SHOWN"


async def test_get_state_absent_returns_none(aggregates_store: AggregateStore):
    assert await aggregates_store.get_state("proj", "no-such-fp") is None


async def test_rebuild_is_idempotent(
    events_store: MasterEventStore, aggregates_store: AggregateStore
):
    await events_store.ingest(prime("POTENTIALLY_FIXED"))
    await aggregates_store.rebuild()
    first = await aggregates_store.get_state("proj", FP)
    await aggregates_store.rebuild()
    second = await aggregates_store.get_state("proj", FP)
    assert first == second
    assert first.status == "POTENTIALLY_FIXED"
    assert first.missed_scan_count == 0


async def test_rebuild_after_new_events_updates(
    events_store: MasterEventStore, aggregates_store: AggregateStore
):
    await events_store.ingest(prime("SHOWN"))
    await aggregates_store.rebuild()
    assert (await aggregates_store.get_state("proj", FP)).status == "SHOWN"

    await events_store.ingest(
        [make_event("not_found_in_scope", at=shift_at(BASE_AT, 10), missed_scan_count=3)]
    )
    await aggregates_store.rebuild()
    state = await aggregates_store.get_state("proj", FP)
    assert state.status == "POTENTIALLY_FIXED"
    assert state.missed_scan_count == 3


async def test_list_states_ordered_by_fp(
    events_store: MasterEventStore, aggregates_store: AggregateStore
):
    await events_store.ingest(
        [
            make_event("discovered", project_key="p1", fp="b"),
            make_event("discovered", project_key="p1", fp="a"),
        ]
    )
    await aggregates_store.rebuild()
    states = await aggregates_store.list_states("p1")
    assert [s.fp for s in states] == ["a", "b"]


async def test_list_states_filters_by_last_seen_branch_and_commit(
    events_store: MasterEventStore, aggregates_store: AggregateStore
):
    await events_store.ingest(
        [
            make_event("discovered", fp="a", branch="feature/x", commit="old"),
            make_event("discovered", fp="b", branch="main", commit="abc"),
        ]
    )
    await aggregates_store.rebuild()
    await events_store.ingest(
        [
            make_event(
                "reopened",
                fp="a",
                branch="feature/x",
                commit="abc",
                at=shift_at(BASE_AT, 1),
            )
        ]
    )
    await aggregates_store.rebuild()

    states = await aggregates_store.list_states("proj", branch="feature/x", commit="abc")

    assert [state.fp for state in states] == ["a"]

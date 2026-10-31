"""Контракты MasterEvent: валидация, обязательные поля, enum, UTC.

ADR-0006 §1.4 + ADR-0004 §5.1: 10 событий жизненного цикла + config_policy.
"""

from __future__ import annotations

import pytest
from helpers import FP, make_event, uid
from pydantic import ValidationError

from appsecgate_master.contracts.events import SCHEMA_VERSION, EventType


def test_schema_version_default():
    event = make_event("discovered")
    assert event.schema_version == SCHEMA_VERSION == 1


@pytest.mark.parametrize(
    "expected",
    [
        "discovered",
        "reaffirmed",
        "not_found_in_scope",
        "verify_fixed",
        "verify_not_fixed",
        "verify_wont_fix",
        "suppressed",
        "suppression_expired",
        "unsuppressed",
        "reopened",
        "config_policy",
    ],
)
def test_event_type_values(expected: str):
    assert EventType(expected).value == expected


def test_finding_types_excludes_config_policy():
    assert EventType.CONFIG_POLICY not in EventType.finding_types()
    assert len(EventType.finding_types()) == 10


def test_finding_event_requires_fp():
    with pytest.raises(ValidationError):
        make_event("discovered", fp=None)


def test_config_policy_allows_no_fp():
    event = make_event("config_policy", fp=None, policy={"gates": {"ci": {"block": True}}})
    assert event.fp is None
    assert event.policy == {"gates": {"ci": {"block": True}}}


def test_suppressed_requires_scope():
    with pytest.raises(ValidationError):
        make_event("suppressed")


def test_verify_wont_fix_requires_note():
    with pytest.raises(ValidationError):
        make_event("verify_wont_fix")


def test_unsuppressed_requires_note():
    with pytest.raises(ValidationError):
        make_event("unsuppressed")


def test_rejects_unknown_event_type():
    with pytest.raises(ValidationError):
        make_event("unknown_event")


@pytest.mark.parametrize("at", ["2026-10-31T12:00:00Z", "2026-10-31T12:00:00+00:00"])
def test_accepts_utc_timestamps(at: str):
    assert make_event("discovered", at=at).at == at


@pytest.mark.parametrize("at", ["2026-10-31T12:00:00+03:00", "2026-10-31T12:00:00"])
def test_rejects_non_utc_timestamps(at: str):
    with pytest.raises(ValidationError):
        make_event("discovered", at=at)


def test_rejects_malformed_timestamp():
    with pytest.raises(ValidationError):
        make_event("discovered", at="tomorrow")


def test_rejects_non_uuid_client_event_id():
    with pytest.raises(ValidationError):
        make_event("discovered", client_event_id="not-a-uuid")


def test_sort_key_uses_at_then_id_tiebreak():
    base = "2026-10-31T12:00:00Z"
    earlier = make_event(
        "discovered", at=base, client_event_id="00000000-0000-4000-8000-000000000001"
    )
    later = make_event("discovered", at="2026-10-31T12:05:00Z", client_event_id=uid())
    tie = make_event("discovered", at=base, client_event_id="00000000-0000-4000-8000-000000000002")
    assert earlier.sort_key() < later.sort_key()
    assert earlier.sort_key() < tie.sort_key()  # tie-break: client_event_id
    assert tie.sort_key() == ("2026-10-31T12:00:00Z", "00000000-0000-4000-8000-000000000002")


def test_snapshot_format_parses_event_id():
    """Snapshot-событие §3.3: event_id задаётся отдельно, валидные UUID."""
    event = make_event("verify_fixed", event_id=uid(), fp=FP)
    assert event.event_id is not None

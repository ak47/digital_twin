"""Session idle digest eligibility."""

from datetime import UTC, datetime, timedelta

from digital_twin.session_digest import should_send_idle_digest


def test_no_messages() -> None:
    now = datetime(2026, 4, 5, 12, 0, tzinfo=UTC)
    la = now - timedelta(hours=2)
    assert not should_send_idle_digest(
        now=now,
        last_activity=la,
        idle_digest_sent_at=None,
        has_messages=False,
        idle=timedelta(hours=1),
    )


def test_not_idle_yet() -> None:
    now = datetime(2026, 4, 5, 12, 0, tzinfo=UTC)
    la = now - timedelta(minutes=30)
    assert not should_send_idle_digest(
        now=now,
        last_activity=la,
        idle_digest_sent_at=None,
        has_messages=True,
        idle=timedelta(hours=1),
    )


def test_idle_never_sent() -> None:
    now = datetime(2026, 4, 5, 12, 0, tzinfo=UTC)
    la = now - timedelta(hours=2)
    assert should_send_idle_digest(
        now=now,
        last_activity=la,
        idle_digest_sent_at=None,
        has_messages=True,
        idle=timedelta(hours=1),
    )


def test_already_sent_for_this_idle_window() -> None:
    now = datetime(2026, 4, 5, 14, 0, tzinfo=UTC)
    la = datetime(2026, 4, 5, 10, 0, tzinfo=UTC)
    sent = datetime(2026, 4, 5, 11, 5, tzinfo=UTC)
    assert not should_send_idle_digest(
        now=now,
        last_activity=la,
        idle_digest_sent_at=sent.isoformat().replace("+00:00", "Z"),
        has_messages=True,
        idle=timedelta(hours=1),
    )


def test_new_chat_after_digest_allows_future_digest() -> None:
    now = datetime(2026, 4, 5, 14, 0, tzinfo=UTC)
    la = datetime(2026, 4, 5, 13, 0, tzinfo=UTC)
    sent = datetime(2026, 4, 5, 11, 0, tzinfo=UTC)
    assert should_send_idle_digest(
        now=now,
        last_activity=la,
        idle_digest_sent_at=sent.isoformat().replace("+00:00", "Z"),
        has_messages=True,
        idle=timedelta(hours=1),
    )

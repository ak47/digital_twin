from __future__ import annotations

from datetime import timedelta

from digital_twin import conversation_store, escalation_email
from digital_twin.time_utils import utc_now


def test_escalation_debounce(sqlite_db, conversation_id, monkeypatch) -> None:
    monkeypatch.setenv("ESCALATION_EMAIL_TO", "owner@example.com")
    monkeypatch.setenv("ESCALATION_EMAIL_DEBOUNCE_MINUTES", "60")
    from digital_twin.settings import reset_settings_cache

    reset_settings_cache()

    conversation_store.insert_message(
        conversation_id, "twin", "need help", needs_attention=True
    )
    conversation_store.set_needs_attention(conversation_id, flag=True)

    assert conversation_store.should_send_escalation_email(conversation_id) is True

    # Simulate recent send
    cid = conversation_store.ensure_conversation(conversation_id)
    with conversation_store.get_db_session() as session:
        conv = session.get(conversation_store.ConversationRow, cid)
        assert conv is not None
        conv.last_escalation_email_at = utc_now()
        session.commit()

    assert conversation_store.should_send_escalation_email(conversation_id) is False


def test_send_escalation_email_skips_without_recipients(sqlite_db, conversation_id, monkeypatch) -> None:
    monkeypatch.delenv("ESCALATION_EMAIL_TO", raising=False)
    monkeypatch.delenv("RESUME_BOT_DIGEST_EMAIL_TO", raising=False)
    from digital_twin.settings import reset_settings_cache

    reset_settings_cache()

    conversation_store.set_needs_attention(conversation_id, flag=True)
    assert escalation_email.send_escalation_email(conversation_id, preview="p", visitor_message="v") is False

from __future__ import annotations

from digital_twin import conversation_store


def test_insert_and_get_messages_order(sqlite_db, conversation_id) -> None:
    conversation_store.insert_message(conversation_id, "visitor", "hello")
    conversation_store.insert_message(conversation_id, "twin", "hi there")
    rows = conversation_store.get_messages(conversation_id)
    assert len(rows) == 2
    assert rows[0]["role"] == "visitor"
    assert rows[1]["role"] == "twin"
    assert rows[0]["id"] < rows[1]["id"]


def test_default_visitor_name_rando(sqlite_db, conversation_id) -> None:
    conversation_store.insert_message(conversation_id, "visitor", "hi")
    rows = conversation_store.get_messages(conversation_id)
    assert rows[0]["conversation_name"] == "Rando"


def test_visitor_name_update(sqlite_db, conversation_id) -> None:
    conversation_store.insert_message(conversation_id, "visitor", "hi")
    conversation_store.insert_message(
        conversation_id, "visitor", "again", visitor_name="Alex"
    )
    rows = conversation_store.get_messages(conversation_id)
    assert rows[-1]["conversation_name"] == "Alex"


def test_poll_after_id(sqlite_db, conversation_id) -> None:
    first = conversation_store.insert_message(conversation_id, "visitor", "one")
    conversation_store.insert_message(conversation_id, "twin", "two")
    polled = conversation_store.get_messages(conversation_id, after_id=first["id"])
    assert len(polled) == 1
    assert polled[0]["role"] == "twin"


def test_list_and_open_conversation(sqlite_db, conversation_id) -> None:
    conversation_store.insert_message(conversation_id, "visitor", "question")
    conversation_store.insert_message(conversation_id, "twin", "answer", needs_attention=True)
    summaries = conversation_store.list_conversations()
    assert len(summaries) == 1
    assert summaries[0]["needs_attention"] is True
    opened = conversation_store.open_conversation(conversation_id)
    assert all(m["read"] for m in opened)
    summaries = conversation_store.list_conversations()
    assert summaries[0]["needs_attention"] is False


def test_owner_message_and_resolve(sqlite_db, conversation_id) -> None:
    conversation_store.insert_message(conversation_id, "visitor", "help")
    owner = conversation_store.insert_owner_message(conversation_id, "Owner here")
    assert owner["role"] == "owner"
    conversation_store.resolve_conversation(conversation_id)
    rows = conversation_store.get_messages(conversation_id)
    assert all(not r["needs_attention"] for r in rows)


def test_strip_escalation_marker() -> None:
    text, flagged = conversation_store.strip_escalation_marker("Please wait <<ESCALATE>>")
    assert flagged is True
    assert "<<ESCALATE>>" not in text

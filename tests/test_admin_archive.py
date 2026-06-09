from __future__ import annotations

import uuid

from digital_twin import conversation_store


def test_archive_restore_and_export(sqlite_db) -> None:
    cid = str(uuid.uuid4())
    conversation_store.insert_message(cid, "visitor", "archive me")
    conversation_store.insert_message(cid, "twin", "reply")

    export_before = conversation_store.export_messages_jsonl()
    assert cid in export_before
    assert export_before.count("\n") >= 2

    conversation_store.archive_conversation(cid)
    assert conversation_store.get_messages(cid) == []
    assert conversation_store.list_conversations() == []

    archived = conversation_store.list_archived_conversations()
    assert len(archived) == 1
    assert archived[0]["conversation_id"] == cid

    conversation_store.restore_conversation(cid)
    rows = conversation_store.get_messages(cid)
    assert len(rows) == 2

from digital_twin import session_store
from digital_twin.settings import reset_settings_cache


def test_session_store_in_memory_round_trip(monkeypatch) -> None:
    monkeypatch.setenv("GCS_SESSIONS_BUCKET", "")
    reset_settings_cache()

    sid = session_store.new_session_id()
    msgs = [{"role": "user", "text": "hi"}, {"role": "assistant", "text": "hello"}]
    session_store.save_messages(sid, msgs)
    loaded = session_store.load_messages(sid)

    assert loaded == msgs


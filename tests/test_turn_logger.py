"""Phase 9: unit test for the transcript storage opt-in (Phase 8)."""

from voicedesk_voice import turn_logger


def test_stored_text_redacts_by_default(monkeypatch):
    monkeypatch.setattr(turn_logger, "STORE_FULL_TRANSCRIPTS", False)
    text = "My order number is 12345 and my address is 1 Main St."
    stored = turn_logger._stored_text(text)
    assert text not in stored
    assert str(len(text)) in stored


def test_stored_text_keeps_full_text_when_opted_in(monkeypatch):
    monkeypatch.setattr(turn_logger, "STORE_FULL_TRANSCRIPTS", True)
    text = "My order number is 12345."
    assert turn_logger._stored_text(text) == text

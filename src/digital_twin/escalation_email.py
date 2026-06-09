"""Send immediate escalation emails when a conversation needs attention."""

from __future__ import annotations

import logging

from digital_twin import conversation_store
from digital_twin.session_digest import _send_gmail_digest
from digital_twin.settings import get_settings

logger = logging.getLogger(__name__)


def _recipients() -> list[str]:
    raw = get_settings().escalation_email_to.strip()
    return [e.strip() for e in raw.split(",") if e.strip()]


def send_escalation_email(conversation_id: str, *, preview: str, visitor_message: str) -> bool:
    """Send escalation email if debounce allows. Returns True when sent."""
    if not conversation_store.should_send_escalation_email(conversation_id):
        return False
    recipients = _recipients()
    if not recipients:
        logger.warning(
            "Escalation email skipped: no recipients configured",
            extra={"event": "escalation_email_skipped", "conversation_id": conversation_id},
        )
        return False
    subject = f"Digital twin needs attention — {conversation_id[:8]}"
    body = (
        f"Conversation: {conversation_id}\n\n"
        f"Latest visitor message:\n{visitor_message}\n\n"
        f"Twin reply preview:\n{preview}\n"
    )
    try:
        _send_gmail_digest(
            to_emails=recipients,
            subject=subject,
            attachment_filename=f"escalation-{conversation_id}.txt",
            attachment_text=body,
        )
        conversation_store.mark_escalation_email_sent(conversation_id)
        logger.info(
            "Escalation email sent",
            extra={"event": "escalation_email_sent", "conversation_id": conversation_id},
        )
        return True
    except Exception as e:
        logger.error(
            "Escalation email failed: %s",
            e,
            extra={"event": "escalation_email_failed", "conversation_id": conversation_id},
            exc_info=True,
        )
        return False

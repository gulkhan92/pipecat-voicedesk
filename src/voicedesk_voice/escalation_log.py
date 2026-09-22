"""Phase 5: writes a structured escalation summary, not a raw transcript.

Called from the escalation flow node in call_flow.py.
"""

import asyncio

import psycopg

from voicedesk_retrieval.config import DATABASE_URL


def build_summary(*, caller_name: str | None, intent: str | None, reason: str, attempts: int) -> str:
    who = caller_name or "an unidentified caller"
    what = intent or "an unspecified issue"
    return (
        f"{who} called about: {what}. Escalated after {attempts} clarification "
        f"attempt(s). Reason: {reason}."
    )


def _write_row(
    *,
    session_id: int | None,
    caller_name: str | None,
    intent: str | None,
    reason: str,
    attempts: int,
    summary: str,
) -> None:
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute(
            """
            INSERT INTO escalations (
                session_id, caller_name, intent, reason, clarification_attempts, summary
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (session_id, caller_name, intent, reason, attempts, summary),
        )
        conn.commit()


async def log_escalation(
    *,
    session_id: int | None,
    caller_name: str | None,
    intent: str | None,
    reason: str,
    attempts: int,
) -> str:
    """Write the escalation row and return the summary that was logged."""
    summary = build_summary(caller_name=caller_name, intent=intent, reason=reason, attempts=attempts)
    await asyncio.to_thread(
        _write_row,
        session_id=session_id,
        caller_name=caller_name,
        intent=intent,
        reason=reason,
        attempts=attempts,
        summary=summary,
    )
    return summary

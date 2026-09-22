"""Phase 7: structured per-session logging to call_sessions.

Session start is logged as soon as the call begins; turn/provider counts
accumulate in the shared SessionState as the call progresses (see
TurnLogger and CallFlow); the row is finalized when the call ends.
"""

import asyncio

import psycopg

from voicedesk_retrieval.config import DATABASE_URL
from voicedesk_voice.session_state import SessionState


def _insert_session() -> int:
    with psycopg.connect(DATABASE_URL) as conn:
        row = conn.execute(
            "INSERT INTO call_sessions DEFAULT VALUES RETURNING id"
        ).fetchone()
        conn.commit()
        return row[0]


def _finalize_session(
    session_id: int, *, turn_count: int, providers_used: list[str], escalated: bool, escalation_reason: str | None
) -> None:
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute(
            """
            UPDATE call_sessions
            SET ended_at = now(),
                turn_count = %s,
                providers_used = %s,
                escalated = %s,
                escalation_reason = %s
            WHERE id = %s
            """,
            (turn_count, providers_used, escalated, escalation_reason, session_id),
        )
        conn.commit()


async def start_session() -> int:
    """Insert a new call_sessions row and return its id."""
    return await asyncio.to_thread(_insert_session)


async def end_session(session_state: SessionState) -> None:
    """Finalize the call_sessions row for this session."""
    if session_state.session_id is None:
        return
    await asyncio.to_thread(
        _finalize_session,
        session_state.session_id,
        turn_count=session_state.turn_count,
        providers_used=sorted(session_state.providers_used),
        escalated=session_state.escalated,
        escalation_reason=session_state.escalation_reason,
    )

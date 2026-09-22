"""Phase 4: logs provider, token usage, and retrieval hits for every turn.

Sits downstream of the LLM switcher (llm -> turn_logger -> tts), so it sees
the LLMTextFrame chunks, the LLMUsageMetricsData the active provider reports,
and the LLMFullResponseEndFrame that closes out the turn.
"""

import asyncio

import psycopg
from loguru import logger
from pipecat.frames.frames import (
    Frame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    MetricsFrame,
)
from pipecat.metrics.metrics import LLMUsageMetricsData
from pipecat.pipeline.llm_switcher import LLMSwitcher
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from voicedesk_retrieval.config import DATABASE_URL
from voicedesk_voice.config import STORE_FULL_TRANSCRIPTS
from voicedesk_voice.session_state import SessionState
from voicedesk_voice.turn_state import TurnState


def _stored_text(text: str) -> str:
    """The caller's/agent's words are sensitive; store the text itself only
    when explicitly opted in (STORE_FULL_TRANSCRIPTS=true). Otherwise keep
    just a length, which is enough for the analytics dashboard to report
    call volume and response length without retaining what was said.
    """
    if STORE_FULL_TRANSCRIPTS:
        return text
    return f"[not stored, {len(text)} chars]"


class TurnLogger(FrameProcessor):
    """Writes one call_turns row per completed conversational turn, and
    rolls the turn count/provider into the session's SessionState (Phase 7)
    for the coarser call_sessions summary written at call end.
    """

    def __init__(
        self,
        turn_state: TurnState,
        llm_switcher: LLMSwitcher,
        session_state: SessionState,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._turn_state = turn_state
        self._llm_switcher = llm_switcher
        self._session_state = session_state
        self._provider = "unknown"
        self._response_text: list[str] = []
        self._prompt_tokens: int | None = None
        self._completion_tokens: int | None = None
        self._total_tokens: int | None = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMFullResponseStartFrame):
            # Captured here, not when the turn is logged: by the time
            # LLMFullResponseEndFrame arrives, a failed request may already
            # have triggered a failover, which would otherwise misattribute
            # this turn to the provider it switched to rather than the one
            # that actually (attempted to) handle it.
            self._provider = getattr(self._llm_switcher.active_llm, "PROVIDER_NAME", "unknown")
            self._response_text = []
            self._prompt_tokens = None
            self._completion_tokens = None
            self._total_tokens = None
        elif isinstance(frame, LLMTextFrame):
            self._response_text.append(frame.text)
        elif isinstance(frame, MetricsFrame):
            for data in frame.data:
                if isinstance(data, LLMUsageMetricsData):
                    self._prompt_tokens = data.value.prompt_tokens
                    self._completion_tokens = data.value.completion_tokens
                    self._total_tokens = data.value.total_tokens
        elif isinstance(frame, LLMFullResponseEndFrame):
            await self._log_turn()

        await self.push_frame(frame, direction)

    async def _log_turn(self) -> None:
        if not self._turn_state.transcript:
            return

        provider = self._provider
        response_text = "".join(self._response_text).strip()

        try:
            await asyncio.to_thread(
                self._write_row,
                session_id=self._session_state.session_id,
                transcript=_stored_text(self._turn_state.transcript),
                response_text=_stored_text(response_text) if response_text else None,
                provider=provider,
                prompt_tokens=self._prompt_tokens,
                completion_tokens=self._completion_tokens,
                total_tokens=self._total_tokens,
                retrieval_hit_count=self._turn_state.retrieval_hit_count,
                retrieval_top_score=self._turn_state.retrieval_top_score,
            )
            self._session_state.turn_count += 1
            self._session_state.providers_used.add(provider)
        except Exception as e:
            logger.warning(f"Failed to log call turn to the database: {e}")

        self._turn_state.transcript = ""
        self._turn_state.retrieval_hit_count = 0
        self._turn_state.retrieval_top_score = None

    @staticmethod
    def _write_row(
        *,
        session_id: int | None,
        transcript: str,
        response_text: str | None,
        provider: str,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        total_tokens: int | None,
        retrieval_hit_count: int,
        retrieval_top_score: float | None,
    ) -> None:
        with psycopg.connect(DATABASE_URL) as conn:
            conn.execute(
                """
                INSERT INTO call_turns (
                    session_id, transcript, response_text, llm_provider,
                    prompt_tokens, completion_tokens, total_tokens,
                    retrieval_hit_count, retrieval_top_score
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    session_id,
                    transcript,
                    response_text,
                    provider,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    retrieval_hit_count,
                    retrieval_top_score,
                ),
            )
            conn.commit()

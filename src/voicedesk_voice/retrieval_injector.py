"""Phase 4/5: grounds each turn in the support knowledge base before the LLM
runs, and keeps conversation history bounded.

Sits between the user context aggregator and the LLM switcher
(user_aggregator -> retrieval_injector -> llm_switcher). On every
LLMContextFrame it embeds the caller's latest message, retrieves the top
matching support_kb entries via the Phase 1 retrieval module, rewrites a
compact grounding message into the context, and trims conversational history
to the last few turns, since unbounded context directly increases both
latency and token usage in a voice conversation.

Grounding is gated by ``TurnState.retrieval_enabled`` (Phase 5): only the
knowledge-base-grounded flow nodes want it, and only our own previously
injected grounding message is ever removed. Every other message, including
a Pipecat Flow's task_messages for the current node, is left exactly where
it is, so this stays safe to run underneath a FlowManager.
"""

import asyncio
from contextlib import contextmanager

from loguru import logger
from pipecat.frames.frames import Frame, LLMContextFrame
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.utils.tracing.setup import is_tracing_available

from voicedesk_retrieval.retrieval import search
from voicedesk_voice.config import MAX_HISTORY_TURNS, RETRIEVAL_TOP_K
from voicedesk_voice.turn_state import TurnState


@contextmanager
def _retrieval_span(query: str):
    """No-op unless tracing is enabled; otherwise a child span of the
    current turn span (Phase 7), so retrieval shows up in Jaeger alongside
    the STT/LLM/TTS spans Pipecat's services already produce.
    """
    if not is_tracing_available():
        yield None
        return

    from opentelemetry import trace

    tracer = trace.get_tracer("voicedesk.retrieval")
    with tracer.start_as_current_span("retrieval") as span:
        span.set_attribute("retrieval.query", query)
        yield span

GROUNDING_HEADER = (
    "Relevant support information (use only this to answer; if it doesn't "
    "cover the caller's question, say you're not sure and offer to escalate):"
)


def _is_grounding_message(message: object) -> bool:
    return (
        isinstance(message, dict)
        and message.get("role") == "system"
        and isinstance(message.get("content"), str)
        and message["content"].startswith(GROUNDING_HEADER)
    )


class RetrievalContextInjector(FrameProcessor):
    """Grounds each turn in the support knowledge base before the LLM runs."""

    def __init__(
        self,
        turn_state: TurnState,
        *,
        top_k: int = RETRIEVAL_TOP_K,
        max_history_turns: int = MAX_HISTORY_TURNS,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._turn_state = turn_state
        self._top_k = top_k
        self._max_history_turns = max_history_turns

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMContextFrame) and not frame.speculation:
            query = self._last_user_text(frame.context)
            if query:
                await self._ground(frame.context, query)

        await self.push_frame(frame, direction)

    @staticmethod
    def _last_user_text(context: LLMContext) -> str:
        for message in reversed(context.messages):
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            content = message.get("content")
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                parts = [
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                ]
                return " ".join(p for p in parts if p).strip()
        return ""

    async def _ground(self, context: LLMContext, query: str) -> None:
        self._turn_state.transcript = query

        hits = []
        if self._turn_state.retrieval_enabled:
            with _retrieval_span(query) as span:
                try:
                    hits = await asyncio.to_thread(search, query, self._top_k)
                except Exception as e:
                    logger.warning(f"Retrieval failed, continuing without grounding: {e}")
                if span is not None:
                    span.set_attribute("retrieval.hit_count", len(hits))
                    if hits:
                        span.set_attribute("retrieval.top_score", hits[0].similarity)

        self._turn_state.retrieval_hit_count = len(hits)
        self._turn_state.retrieval_top_score = hits[0].similarity if hits else None

        # Drop only our own earlier grounding message. Everything else,
        # greeting/task instructions, a Pipecat Flow's task_messages, prior
        # conversation turns, is left untouched and in place.
        messages = [m for m in context.messages if not _is_grounding_message(m)]

        # Trim conversational (user/assistant) turns beyond the cap, without
        # disturbing where any other message (e.g. a flow's task_messages)
        # sits in the list.
        convo_indices = [
            i for i, m in enumerate(messages) if isinstance(m, dict) and m.get("role") in ("user", "assistant")
        ]
        max_messages = self._max_history_turns * 2
        if len(convo_indices) > max_messages:
            drop = set(convo_indices[: len(convo_indices) - max_messages])
            messages = [m for i, m in enumerate(messages) if i not in drop]

        if hits:
            grounding_lines = "\n".join(
                f"{i + 1}. Q: {hit.instruction}\n   A: {hit.response}"
                for i, hit in enumerate(hits)
            )
            grounding_message = {
                "role": "system",
                "content": f"{GROUNDING_HEADER}\n{grounding_lines}",
            }
            # Right before the current (final) user message, so it's the
            # freshest thing the model reads before answering.
            insert_at = (
                len(messages) - 1
                if messages and messages[-1].get("role") == "user"
                else len(messages)
            )
            messages.insert(insert_at, grounding_message)

        context.set_messages(messages)

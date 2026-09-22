"""Phase 2 placeholder LLM step: echoes the caller's transcript back to them.

Stands in for the real provider-router + retrieval-grounded LLM call that
Phase 4 wires in, so the STT -> TTS round trip (and VAD-driven interruption)
can be verified end to end before any LLM provider is involved.
"""

from pipecat.frames.frames import (
    Frame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.llm_service import LLMService


class EchoLLMService(LLMService):
    """Turns the latest user message in the context into a spoken echo."""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMContextFrame):
            user_text = self._last_user_text(frame.context)
            await self.push_frame(LLMFullResponseStartFrame())
            if user_text:
                await self.push_frame(LLMTextFrame(f"You said: {user_text}"))
            await self.push_frame(LLMFullResponseEndFrame())
        else:
            await self.push_frame(frame, direction)

    @staticmethod
    def _last_user_text(context: LLMContext) -> str:
        for message in reversed(context.messages):
            if message.get("role") != "user":
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

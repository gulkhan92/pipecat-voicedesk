"""Phase 3 STT layer: Groq Whisper primary, local faster-whisper fallback.

Uses Pipecat's built-in ``ServiceSwitcher`` with a failover strategy so the
pipeline automatically moves to the local model when the Groq service errors
out or is rate limited, and stays there until the cooldown in
``GROQ_STT_RECOVERY_SECS`` lets it try Groq again.
"""

import asyncio

from loguru import logger
from pipecat.frames.frames import TranscriptionFrame
from pipecat.pipeline.service_switcher import ServiceSwitcher, ServiceSwitcherStrategyFailover
from pipecat.services.groq.stt import GroqSTTService
from pipecat.services.whisper.stt import WhisperSTTService
from pipecat.utils.time import time_now_iso8601

from voicedesk_voice.config import (
    GROQ_API_KEY,
    GROQ_STT_MODEL,
    GROQ_STT_RECOVERY_SECS,
    WHISPER_FALLBACK_MODEL,
)


class GroqSTTServiceWithFailover(GroqSTTService):
    """Groq STT that reports failures in a way ``ServiceSwitcher`` can act on.

    ``GroqSTTService.run_stt`` (inherited from ``BaseWhisperSTTService``)
    catches its own exceptions and yields a plain ``ErrorFrame`` with no
    ``exception`` attached, which leaves the frame uncategorized and never
    marks the service unusable, so a ``ServiceSwitcherStrategyFailover``
    never fires. This override reports the real exception through
    ``push_error(force_treat_as_permanent=True)`` instead, which does.
    """

    async def run_stt(self, audio: bytes):
        try:
            await self.start_processing_metrics()
            response = await self._transcribe(audio)
            await self.stop_processing_metrics()
        except Exception as e:
            await self.push_error(
                f"Groq STT request failed: {e}",
                exception=e,
                force_treat_as_permanent=True,
            )
            return

        text = response.text.strip()
        if text:
            yield TranscriptionFrame(text, self._user_id, time_now_iso8601(), result=response)


def build_stt_switcher() -> ServiceSwitcher:
    """Build the Groq-primary, local-fallback STT pipeline stage."""
    groq_stt = GroqSTTServiceWithFailover(
        # The OpenAI-compatible client used under the hood requires a non-empty
        # key at construction time even when one isn't configured yet; a
        # placeholder lets the service build and fail (then fail over) cleanly
        # on the first real request instead of crashing pipeline setup.
        api_key=GROQ_API_KEY or "not-configured",
        settings=GroqSTTServiceWithFailover.Settings(model=GROQ_STT_MODEL),
    )
    whisper_stt = WhisperSTTService(
        # This machine has no usable CUDA runtime (faster-whisper's "auto"
        # device probe still tries to load cuBLAS and fails), so pin CPU
        # inference explicitly.
        device="cpu",
        compute_type="int8",
        settings=WhisperSTTService.Settings(model=WHISPER_FALLBACK_MODEL),
    )

    switcher = ServiceSwitcher(
        services=[groq_stt, whisper_stt],
        strategy_type=ServiceSwitcherStrategyFailover,
    )

    @switcher.strategy.event_handler("on_service_switched")
    async def on_service_switched(strategy, service):
        logger.warning(f"STT failover: now using {service.name}")

    @groq_stt.event_handler("on_usable_changed")
    async def on_groq_usable_changed(processor, is_usable):
        if is_usable:
            return
        logger.warning(
            f"Groq STT unusable, will retry in {GROQ_STT_RECOVERY_SECS:.0f}s "
            "(pipeline continues on the local Whisper fallback in the meantime)"
        )

        async def _recover():
            await asyncio.sleep(GROQ_STT_RECOVERY_SECS)
            await processor.set_usable(True)
            logger.info("Groq STT eligible again after cooldown")

        asyncio.create_task(_recover())

    return switcher

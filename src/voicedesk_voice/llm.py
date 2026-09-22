"""Phase 4 LLM provider layer: Groq primary, Gemini fallback.

Mirrors the Phase 3 STT failover pattern: a Pipecat ``LLMSwitcher`` with a
failover strategy moves to the next provider whenever the active one reports
an error it can't recover from (an actual API error, or this module's own
Redis-tracked per-minute request budget), and recovers back after a cooldown.

Unlike the STT services, GroqLLMService and GoogleLLMService already attach
the real exception to their error frames, so the framework's own error
classification handles real API failures without needing the same
swallowed-exception workaround Phase 3 needed for STT, with one gap this
module closes: ``ErrorCategory.RATE_LIMIT`` and ``.QUOTA`` are not in the
framework's "permanent" set (a rate limit often clears on its own), so on
their own they would *not* mark a service unusable and would never trigger
``ServiceSwitcherStrategyFailover``. Phase 8 explicitly wants a rate-limited
provider to fail over, so ``_QuotaGatedLLMMixin`` treats those two
categories as failover-worthy too.
"""

import asyncio

from loguru import logger
from pipecat.frames.frames import ErrorFrame, LLMContextFrame
from pipecat.pipeline.llm_switcher import LLMSwitcher
from pipecat.pipeline.service_switcher import ServiceSwitcherStrategyFailover
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.google.llm import GoogleLLMService
from pipecat.services.groq.llm import GroqLLMService
from pipecat.utils.errors import ErrorCategory, classify_http_exception

from voicedesk_voice import quota
from voicedesk_voice.config import (
    GEMINI_API_KEY,
    GEMINI_LLM_MODEL,
    GEMINI_LLM_RPM_LIMIT,
    GROQ_API_KEY,
    GROQ_LLM_MODEL,
    GROQ_LLM_RPM_LIMIT,
    LLM_MAX_TOKENS,
    LLM_PROVIDER_RECOVERY_SECS,
)

SYSTEM_INSTRUCTION = (
    "You are a concise, professional customer support voice agent for an "
    "e-commerce retailer. Your responses are spoken aloud, so answer in one "
    "or two short, natural sentences with no formatting, bullet points, or "
    "emojis. Ground every answer in the support information you are given; "
    "if it does not cover the caller's question, say you are not sure and "
    "offer to escalate to a human agent rather than guessing."
)


# The framework only marks a service unusable (and so failover-eligible) for
# "permanent" categories (auth, authorization, invalid request). A rate limit
# or exhausted quota should also send this pipeline to the backup provider,
# so they're added here rather than waiting for the primary to recover.
_FAILOVER_CATEGORIES = frozenset({ErrorCategory.RATE_LIMIT, ErrorCategory.QUOTA})


class _QuotaGatedLLMMixin:
    """Adds a proactive Redis-tracked requests-per-minute budget check, and
    treats a real rate-limit/quota error from the provider as failover-worthy.

    The budget check runs before the API call, on top of the framework's own
    reactive failover on real errors, so a provider is skipped once it is
    *about* to be rate limited rather than only after the first failed
    request.
    """

    PROVIDER_NAME: str
    RPM_LIMIT: int

    async def process_frame(self, frame, direction: FrameDirection):
        if isinstance(frame, LLMContextFrame):
            if await quota.is_quota_exceeded(self.PROVIDER_NAME, self.RPM_LIMIT):
                await self.push_error(
                    f"{self.PROVIDER_NAME} LLM request budget exceeded "
                    f"({self.RPM_LIMIT}/min)",
                    force_treat_as_permanent=True,
                )
                return
            await quota.record_request(self.PROVIDER_NAME)

        await super().process_frame(frame, direction)

    async def push_error_frame(self, error: ErrorFrame, force_treat_as_permanent: bool = False):
        if not force_treat_as_permanent and error.category is None and error.exception is not None:
            category = self._classify_error(error.exception) or classify_http_exception(
                error.exception
            )
            if category in _FAILOVER_CATEGORIES:
                force_treat_as_permanent = True
        await super().push_error_frame(error, force_treat_as_permanent=force_treat_as_permanent)


class GroqLLMServiceWithQuota(_QuotaGatedLLMMixin, GroqLLMService):
    """Groq LLM service with a Redis-tracked request budget."""

    PROVIDER_NAME = "groq"
    RPM_LIMIT = GROQ_LLM_RPM_LIMIT


class GeminiLLMServiceWithQuota(_QuotaGatedLLMMixin, GoogleLLMService):
    """Gemini LLM service with a Redis-tracked request budget."""

    PROVIDER_NAME = "gemini"
    RPM_LIMIT = GEMINI_LLM_RPM_LIMIT


def build_llm_switcher() -> LLMSwitcher:
    """Build the Groq-primary, Gemini-fallback LLM pipeline stage."""
    groq_llm = GroqLLMServiceWithQuota(
        # A placeholder key lets the service build even with no GROQ_API_KEY
        # configured; the first real request then fails cleanly (and fails
        # over) instead of crashing pipeline setup, same as the STT service.
        api_key=GROQ_API_KEY or "not-configured",
        settings=GroqLLMServiceWithQuota.Settings(
            model=GROQ_LLM_MODEL,
            system_instruction=SYSTEM_INSTRUCTION,
            max_tokens=LLM_MAX_TOKENS,
        ),
    )
    gemini_llm = GeminiLLMServiceWithQuota(
        api_key=GEMINI_API_KEY or "not-configured",
        settings=GeminiLLMServiceWithQuota.Settings(
            model=GEMINI_LLM_MODEL,
            system_instruction=SYSTEM_INSTRUCTION,
            max_tokens=LLM_MAX_TOKENS,
        ),
    )

    switcher = LLMSwitcher(
        llms=[groq_llm, gemini_llm],
        strategy_type=ServiceSwitcherStrategyFailover,
    )

    @switcher.strategy.event_handler("on_service_switched")
    async def on_service_switched(strategy, service):
        logger.warning(f"LLM failover: now using {service.name}")

    for llm in (groq_llm, gemini_llm):

        def _make_handler(processor):
            async def on_usable_changed(_processor, is_usable):
                if is_usable:
                    return
                logger.warning(
                    f"{processor.PROVIDER_NAME} LLM unusable, will retry in "
                    f"{LLM_PROVIDER_RECOVERY_SECS:.0f}s"
                )

                async def _recover():
                    await asyncio.sleep(LLM_PROVIDER_RECOVERY_SECS)
                    await processor.set_usable(True)
                    logger.info(f"{processor.PROVIDER_NAME} LLM eligible again after cooldown")

                asyncio.create_task(_recover())

            return on_usable_changed

        llm.add_event_handler("on_usable_changed", _make_handler(llm))

    return switcher

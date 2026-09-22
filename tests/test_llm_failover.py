"""Phase 8/9: automated test that a rate-limited Groq response makes the
pipeline continue the call on Gemini, without needing real API credentials.

Two levels:
  - test_rate_limit_category_triggers_failover: a focused unit test of the
    exact bug this module's push_error_frame override fixes (RATE_LIMIT and
    QUOTA aren't in the framework's "permanent" set, so on their own they
    would never mark a provider unusable or trigger failover).
  - test_llm_switcher_fails_over_from_rate_limited_groq_to_gemini: an
    integration test, using Pipecat's own pipecat.tests.utils.run_test
    harness, that drives the real GroqLLMServiceWithQuota /
    GeminiLLMServiceWithQuota through an actual LLMSwitcher and confirms the
    final spoken text comes from Gemini after Groq is rate limited.
"""

import pytest
from pipecat.frames.frames import (
    ErrorFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.tests.utils import SleepFrame, run_test

from voicedesk_voice.llm import GroqLLMServiceWithQuota, build_llm_switcher


class _RateLimitError(Exception):
    """Stands in for a real provider SDK exception carrying a 429 status,
    the same attribute shape pipecat.utils.errors.extract_http_status_code
    looks for.
    """

    status_code = 429


@pytest.mark.asyncio
async def test_rate_limit_category_triggers_failover():
    """A RATE_LIMIT-categorized error must be treated as failover-worthy.

    Patches the ultimate base's push_error_frame (the only class in the MRO
    that defines it) so this exercises just the mixin's escalation logic,
    without needing a live pipeline.
    """
    import pipecat.processors.frame_processor as frame_processor_module

    groq = GroqLLMServiceWithQuota(api_key="not-configured")
    error = ErrorFrame(error="rate limited", exception=_RateLimitError())

    called_with = {}

    async def fake_base_push_error_frame(self, error, force_treat_as_permanent=False):
        called_with["force_treat_as_permanent"] = force_treat_as_permanent

    original_base = frame_processor_module.FrameProcessor.push_error_frame
    frame_processor_module.FrameProcessor.push_error_frame = fake_base_push_error_frame
    try:
        await groq.push_error_frame(error)
    finally:
        frame_processor_module.FrameProcessor.push_error_frame = original_base

    assert called_with["force_treat_as_permanent"] is True


@pytest.mark.asyncio
async def test_llm_switcher_fails_over_from_rate_limited_groq_to_gemini():
    """Groq raises a rate-limit-shaped error on the first turn, which fails
    the switcher over to Gemini (same mechanism proven live against the real
    APIs in Phase 4/5, just without needing real credentials here). Like the
    STT failover in Phase 3, a turn that hits the error is itself lost: the
    switch is reactive, not a retry, so the caller's *next* turn is what
    proves the call carries on: it must reach Gemini and get a response.
    """
    switcher = build_llm_switcher()
    groq_llm, gemini_llm = switcher.llms

    async def groq_raises_rate_limit(self, context):
        raise _RateLimitError("rate limited")

    async def gemini_responds(self, context):
        await self.push_frame(LLMTextFrame("Sure, I can help with that."))

    groq_llm._process_context = groq_raises_rate_limit.__get__(groq_llm)
    gemini_llm._process_context = gemini_responds.__get__(gemini_llm)

    first_turn = LLMContext(messages=[{"role": "user", "content": "I need help with my order."}])
    second_turn = LLMContext(
        messages=[
            {"role": "user", "content": "I need help with my order."},
            {"role": "user", "content": "Hello, are you still there?"},
        ]
    )

    down_frames, _ = await run_test(
        switcher,
        frames_to_send=[
            LLMContextFrame(context=first_turn),
            # Give the first turn's error time to reach the switcher and flip
            # the active service before the second turn is sent. Real calls
            # have this gap for free (caller speech takes seconds); sent back
            # to back, both turns can reach Groq before its failure has been
            # handled.
            SleepFrame(sleep=0.2),
            LLMContextFrame(context=second_turn),
        ],
        start_timeout=10.0,
    )

    assert groq_llm.is_usable is False, "Groq should be marked unusable after the rate limit"
    assert switcher.active_llm is gemini_llm, "switcher should have failed over to Gemini"

    text_frames = [f for f in down_frames if isinstance(f, LLMTextFrame)]
    assert any(f.text == "Sure, I can help with that." for f in text_frames), (
        f"expected the caller's next turn to reach Gemini and get a response; got: {down_frames}"
    )

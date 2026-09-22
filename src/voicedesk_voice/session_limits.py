"""Phase 8: hard call-duration cap and idle-silence timeout.

Both end the session cleanly (cancel the pipeline worker) rather than
leaving a call running indefinitely, whether because the caller never hangs
up or because they went silent and never came back.
"""

import asyncio
from collections.abc import Callable

from loguru import logger
from pipecat.frames.frames import VADUserStartedSpeakingFrame
from pipecat.pipeline.worker import PipelineWorker
from pipecat.processors.idle_frame_processor import IdleFrameProcessor

from voicedesk_voice.config import MAX_CALL_DURATION_SECS, MAX_IDLE_SILENCE_SECS


def build_idle_silence_monitor() -> tuple[IdleFrameProcessor, Callable[[PipelineWorker], None]]:
    """Build a pipeline stage that ends the call after prolonged caller silence.

    Watches for VADUserStartedSpeakingFrame specifically (not just any audio
    frame) so a live connection that is simply quiet, not raw silence
    packets, which keep flowing during a WebRTC/WebSocket call regardless of
    whether anyone is speaking, correctly counts as idle.

    The PipelineWorker to cancel on timeout doesn't exist yet when this
    processor has to be built (it's part of the pipeline the worker wraps),
    so it's bound after construction via the returned ``bind_worker``.

    Returns:
        The processor to place in the pipeline, and a ``bind_worker(worker)``
        function to call once the worker exists.
    """
    worker_ref: list[PipelineWorker] = []

    async def on_idle(_processor: IdleFrameProcessor):
        if not worker_ref:
            return
        logger.warning(f"No caller speech for {MAX_IDLE_SILENCE_SECS:.0f}s, ending the call")
        await worker_ref[0].cancel()

    processor = IdleFrameProcessor(
        callback=on_idle,
        timeout=MAX_IDLE_SILENCE_SECS,
        types=[VADUserStartedSpeakingFrame],
    )

    def bind_worker(worker: PipelineWorker) -> None:
        worker_ref.append(worker)

    return processor, bind_worker


def start_max_duration_watchdog(worker: PipelineWorker) -> asyncio.Task:
    """Schedule a task that ends the call after MAX_CALL_DURATION_SECS."""

    async def _watchdog():
        try:
            await asyncio.sleep(MAX_CALL_DURATION_SECS)
        except asyncio.CancelledError:
            return
        logger.warning(f"Call reached the {MAX_CALL_DURATION_SECS:.0f}s maximum duration, ending it")
        await worker.cancel()

    return asyncio.create_task(_watchdog())

#
# Phase 2-8 voice pipeline for the e-commerce support agent.
#
# Cascade pipeline: transport input -> STT (Groq, local Whisper fallback) ->
# retrieval grounding -> LLM (Groq, Gemini fallback) -> turn logging ->
# TTS (Kokoro, local) -> transport output. Conversation structure (greeting,
# intent capture, resolution, clarification, escalation, closing) is driven
# by the Pipecat Flow in voicedesk_voice.call_flow.
#
# Phase 6: SmallWebRTCTransport is the primary transport for the browser
# client (client/, run with `npm run dev`), for lower latency than
# WebSocket. The WebSocket transport from early development stays available
# too, for the scripted smoke-test client:
#
#     uv run bot.py                  # serves both webrtc and websocket
#
# Browser client connects via POST /start (transport: "webrtc"); the scripted
# test client connects directly to ws://localhost:7860/ws-client (see
# scripts/voice_smoke_test_client.py).
#
# Phase 7: OpenTelemetry traces export to Jaeger (http://localhost:16686),
# with per-turn spans broken down by STT/retrieval/LLM/TTS time. Whisker
# (a live pipeline debugger) is available at https://whisker.pipecat.ai,
# pointed at ws://localhost:9090. Both are dev-only and can be turned off
# via ENABLE_TRACING / ENABLE_WHISKER.
#
# Phase 8: connections require a valid JWT when REQUIRE_AUTH=true (off by
# default here; see scripts/issue_dev_token.py), new calls are rate limited
# per client IP, and a call ends cleanly after MAX_CALL_DURATION_SECS or
# MAX_IDLE_SILENCE_SECS of caller silence. Transcript text is stored only
# when STORE_FULL_TRANSCRIPTS=true; see voicedesk_voice.turn_logger.
#

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.serializers.protobuf import ProtobufFrameSerializer
from pipecat.services.kokoro.tts import KokoroTTSService
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams
from pipecat.workers.runner import WorkerRunner

from voicedesk_voice.auth import AuthError, authenticate_session
from voicedesk_voice.call_flow import CallFlow
from voicedesk_voice.client_ip import get_client_ip
from voicedesk_voice.config import ENABLE_WHISKER, KOKORO_VOICE_ID, WHISKER_PORT
from voicedesk_voice.llm import build_llm_switcher
from voicedesk_voice.observability import setup_pipeline_tracing
from voicedesk_voice.rate_limit import RateLimitExceeded, check_and_record_call_start
from voicedesk_voice.retrieval_injector import RetrievalContextInjector
from voicedesk_voice.session_limits import (
    build_idle_silence_monitor,
    start_max_duration_watchdog,
)
from voicedesk_voice.session_logger import end_session, start_session
from voicedesk_voice.session_state import SessionState
from voicedesk_voice.stt import build_stt_switcher
from voicedesk_voice.turn_logger import TurnLogger
from voicedesk_voice.turn_state import TurnState


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments) -> None:
    """Run the voice bot for this session."""
    logger.info("Starting bot")

    setup_pipeline_tracing()

    stt = build_stt_switcher()

    tts = KokoroTTSService(
        settings=KokoroTTSService.Settings(voice=KOKORO_VOICE_ID),
    )

    llm = build_llm_switcher()

    session_state = SessionState()
    session_state.session_id = await start_session()

    turn_state = TurnState()
    retrieval_injector = RetrievalContextInjector(turn_state)
    turn_logger = TurnLogger(turn_state, llm, session_state)
    idle_silence_monitor, bind_idle_monitor_worker = build_idle_silence_monitor()

    context = LLMContext()
    aggregator_pair = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )
    user_aggregator, assistant_aggregator = aggregator_pair

    pipeline = Pipeline(
        [
            transport.input(),
            idle_silence_monitor,
            stt,
            user_aggregator,
            retrieval_injector,
            llm,
            turn_logger,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        # PipelineWorker builds its own turn-tracking/latency/turn-trace
        # observers and threads a shared TracingContext through every
        # processor's setup(), which is what lets STT/LLM/TTS spans nest
        # under the right turn span. A hand-built, separately wired set of
        # the same observers would use a different TracingContext and every
        # service span would come out parentless.
        enable_tracing=True,
        conversation_id=str(session_state.session_id),
    )
    bind_idle_monitor_worker(worker)

    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)

    await runner.add_workers(worker)

    max_duration_watchdog = start_max_duration_watchdog(worker)

    if ENABLE_WHISKER:
        from pipecat_whisker import WhiskerServer

        whisker = WhiskerServer(port=WHISKER_PORT)
        await runner.add_workers(whisker)
        worker.add_observer(whisker.create_observer(worker))
        logger.info(
            f"Whisker debugger listening on ws://localhost:{WHISKER_PORT} "
            "(view at https://whisker.pipecat.ai)"
        )

    call_flow = CallFlow(
        llm=llm,
        context_aggregator=aggregator_pair,
        worker=worker,
        turn_state=turn_state,
        session_state=session_state,
    )
    await call_flow.start()

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("Client connected")

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("Client disconnected")
        max_duration_watchdog.cancel()
        await end_session(session_state)
        await runner.cancel()

    await runner.run()


async def bot(runner_args: RunnerArguments):
    """Main bot entry point, called by the Pipecat dev runner.

    Authenticates and rate-limits the caller before a transport (and thus a
    pipeline session) is created at all, so a rejected caller never
    consumes an STT/LLM quota slot.
    """
    try:
        subject = authenticate_session(runner_args.body or {})
    except AuthError as e:
        logger.warning(f"Rejected connection: {e}")
        return
    if subject:
        logger.info(f"Authenticated connection for subject={subject}")

    client_ip = get_client_ip(runner_args)
    try:
        await check_and_record_call_start(client_ip)
    except RateLimitExceeded as e:
        logger.warning(f"Rejected connection: {e}")
        return

    transport_params = {
        "webrtc": lambda: TransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
        ),
        "websocket": lambda: FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            serializer=ProtobufFrameSerializer(),
        ),
    }

    transport = await create_transport(runner_args, transport_params)

    await run_bot(transport, runner_args)


if __name__ == "__main__":
    from pipecat.runner.run import main

    main()

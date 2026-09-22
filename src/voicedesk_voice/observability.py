"""Phase 7: OpenTelemetry tracing setup.

Configures the global tracer provider to export to Jaeger. The actual
per-turn spans (and the STT/LLM/TTS child spans Pipecat's services already
produce via ``@traced_stt`` / ``@traced_llm`` / ``@traced_tts``) come from
``PipelineWorker(enable_tracing=True, ...)`` itself: it creates its own
``TurnTrackingObserver`` / ``UserBotLatencyObserver`` / ``TurnTraceObserver``
and threads a shared ``TracingContext`` through every processor's
``FrameProcessorSetup``, which is what makes service spans nest under the
right turn span. A hand-built, separately wired set of the same observers
would use a *different* TracingContext than the one FrameProcessorSetup
hands to services, and every service span would come out parentless.
Retrieval isn't a built-in Pipecat concept, so RetrievalContextInjector adds
its own child span the same way. View traces in Jaeger at
http://localhost:16686.
"""

from loguru import logger
from pipecat.utils.tracing.setup import is_tracing_available, setup_tracing

from voicedesk_voice.config import ENABLE_TRACING, OTLP_ENDPOINT, TRACING_SERVICE_NAME

_tracing_ready = False


def setup_pipeline_tracing() -> bool:
    """Configure the global OpenTelemetry tracer provider, once per process.

    Call before constructing any ``PipelineWorker(enable_tracing=True)``;
    tracing must be configured before the first span is created.
    """
    global _tracing_ready
    if _tracing_ready:
        return True
    if not ENABLE_TRACING:
        logger.info("Tracing disabled (ENABLE_TRACING=false)")
        return False
    if not is_tracing_available():
        logger.warning("opentelemetry-sdk not installed; tracing disabled")
        return False

    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

    exporter = OTLPSpanExporter(endpoint=OTLP_ENDPOINT, insecure=True)
    _tracing_ready = setup_tracing(service_name=TRACING_SERVICE_NAME, exporter=exporter)
    if _tracing_ready:
        logger.info(f"Tracing enabled, exporting to {OTLP_ENDPOINT} (view at http://localhost:16686)")
    return _tracing_ready

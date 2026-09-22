import os

from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.environ.get("GROQ_API_KEY") or None
GROQ_STT_MODEL = os.environ.get("GROQ_STT_MODEL", "whisper-large-v3-turbo")

# Local faster-whisper fallback, used when the Groq STT service is unusable
# (no key, rate limited, or erroring). English-only distilled model keeps
# CPU inference fast enough for a live smoke test.
WHISPER_FALLBACK_MODEL = os.environ.get(
    "WHISPER_FALLBACK_MODEL", "Systran/faster-distil-whisper-medium.en"
)

# Seconds to wait before letting the Groq STT service take traffic again
# after it was marked unusable.
GROQ_STT_RECOVERY_SECS = float(os.environ.get("GROQ_STT_RECOVERY_SECS", "60"))

KOKORO_VOICE_ID = os.environ.get("KOKORO_VOICE_ID", "af_heart")

# Phase 4: LLM provider layer (Groq primary, Gemini fallback).
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or None
GROQ_LLM_MODEL = os.environ.get("GROQ_LLM_MODEL", "openai/gpt-oss-20b")
GEMINI_LLM_MODEL = os.environ.get("GEMINI_LLM_MODEL", "gemini-2.5-flash")

# Voice responses should be short and conversational, not written answers;
# a long response also directly increases time-to-first-audio.
LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "120"))

# Requests-per-minute budget tracked in Redis per provider. A provider that
# hits its budget is treated as unusable and the pipeline fails over, the
# same as an actual rate-limit error from the API.
GROQ_LLM_RPM_LIMIT = int(os.environ.get("GROQ_LLM_RPM_LIMIT", "30"))
GEMINI_LLM_RPM_LIMIT = int(os.environ.get("GEMINI_LLM_RPM_LIMIT", "15"))
LLM_PROVIDER_RECOVERY_SECS = float(os.environ.get("LLM_PROVIDER_RECOVERY_SECS", "60"))

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6380/0")

# Retrieval grounding: how many support_kb hits to inject per turn, and how
# much conversation history to keep. Unbounded context directly increases
# both latency and token usage in a voice conversation.
RETRIEVAL_TOP_K = int(os.environ.get("RETRIEVAL_TOP_K", "3"))
MAX_HISTORY_TURNS = int(os.environ.get("MAX_HISTORY_TURNS", "6"))

# Phase 5: conversation flow. Maximum clarifying follow-up questions before
# the call is escalated to a human agent, so the agent can't loop forever on
# unclear input.
MAX_CLARIFICATION_ATTEMPTS = int(os.environ.get("MAX_CLARIFICATION_ATTEMPTS", "2"))

# Phase 7: observability.
ENABLE_TRACING = os.environ.get("ENABLE_TRACING", "true").lower() == "true"
OTLP_ENDPOINT = os.environ.get("OTLP_ENDPOINT", "http://localhost:4317")
TRACING_SERVICE_NAME = os.environ.get("TRACING_SERVICE_NAME", "pipecat-voicedesk")

# Whisker (https://whisker.pipecat.ai): live pipeline debugger, dev-only.
ENABLE_WHISKER = os.environ.get("ENABLE_WHISKER", "true").lower() == "true"
WHISKER_PORT = int(os.environ.get("WHISKER_PORT", "9090"))

# Phase 8: security and reliability.

# JWT authentication for the client connection. In production this verifies
# a token issued by the platform's own login; REQUIRE_AUTH=false (dev only)
# skips verification so the bot is reachable without standing up that login
# flow first. JWT_SECRET must be set (and kept off any client bundle) when
# REQUIRE_AUTH=true.
REQUIRE_AUTH = os.environ.get("REQUIRE_AUTH", "false").lower() == "true"
JWT_SECRET = os.environ.get("JWT_SECRET") or None
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_SECS = int(os.environ.get("JWT_EXPIRY_SECS", "3600"))

# Rate limiting new call sessions, tracked in Redis per client IP, to protect
# the free-tier STT/LLM quotas from being exhausted by a single source.
CALL_START_RATE_LIMIT = int(os.environ.get("CALL_START_RATE_LIMIT", "5"))
CALL_START_RATE_WINDOW_SECS = int(os.environ.get("CALL_START_RATE_WINDOW_SECS", "60"))

# A call is ended cleanly once it runs this long, or once the caller has been
# silent this long, whichever comes first.
MAX_CALL_DURATION_SECS = float(os.environ.get("MAX_CALL_DURATION_SECS", "900"))
MAX_IDLE_SILENCE_SECS = float(os.environ.get("MAX_IDLE_SILENCE_SECS", "30"))

# Spoken conversations can include sensitive personal information,  so the
# caller's transcript and the agent's spoken response are stored by default
# only as a length (for the analytics dashboard); the full text is opt-in.
STORE_FULL_TRANSCRIPTS = os.environ.get("STORE_FULL_TRANSCRIPTS", "false").lower() == "true"

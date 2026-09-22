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

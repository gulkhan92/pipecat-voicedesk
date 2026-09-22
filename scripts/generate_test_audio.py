"""Phase 2 smoke test helper: synthesize test caller audio with Kokoro TTS.

Generates 16 kHz mono PCM WAV files under data/test_audio/ that
scripts/voice_smoke_test_client.py feeds into the pipeline as if they came
from a real microphone, so the full STT -> TTS round trip can be verified
without a live caller.

Usage:
    uv run python scripts/generate_test_audio.py
"""

import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kokoro_onnx import Kokoro  # noqa: E402
from pipecat.services.kokoro.tts import KOKORO_CACHE_DIR, _ensure_model_files  # noqa: E402

from voicedesk_voice.config import KOKORO_VOICE_ID  # noqa: E402

OUT_DIR = ROOT / "data" / "test_audio"
TARGET_SAMPLE_RATE = 16000

PHRASES = {
    "hello": "Hello, can you hear me?",
    "refund": (
        "What is your return policy for a damaged item? "
        "I received a broken coffee maker last week and I would like to know "
        "how to send it back and get a refund."
    ),
}


def synthesize(kokoro: Kokoro, text: str, out_path: Path) -> None:
    samples, sample_rate = kokoro.create(text, voice=KOKORO_VOICE_ID, lang="en-us", speed=1.0)

    if sample_rate != TARGET_SAMPLE_RATE:
        import numpy as np
        from scipy.signal import resample

        num_samples = int(len(samples) * TARGET_SAMPLE_RATE / sample_rate)
        samples = resample(samples, num_samples).astype(np.float32)

    pcm16 = (samples * 32767).astype("int16")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(TARGET_SAMPLE_RATE)
        wav_file.writeframes(pcm16.tobytes())

    print(f"Wrote {out_path} ({len(pcm16) / TARGET_SAMPLE_RATE:.2f}s)")


def main() -> None:
    model_path = KOKORO_CACHE_DIR / "kokoro-v1.0.onnx"
    voices_path = KOKORO_CACHE_DIR / "voices-v1.0.bin"
    _ensure_model_files(model_path, voices_path)
    kokoro = Kokoro(str(model_path), str(voices_path))

    for name, text in PHRASES.items():
        synthesize(kokoro, text, OUT_DIR / f"{name}.wav")


if __name__ == "__main__":
    main()

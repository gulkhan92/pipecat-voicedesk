"""Phase 2 smoke test client: drives the running bot over the WebSocket
transport with synthetic caller audio and reports what came back.

Confirms:
  1. Audio round-trips correctly (spoken audio comes back after speaking).
  2. Interruption works: sending new caller audio while the bot is still
     speaking stops the in-flight response and starts a new turn.

The user's transcript itself never reaches this client: the aggregator that
sits between STT and the LLM step (LLMUserAggregator, from
LLMContextAggregatorPair) consumes TranscriptionFrame to build LLM context
and does not forward it downstream, so only the bot's synthesized audio (and
its echoed text, "You said: ...") cross the transport back out. Correctness
of the transcript itself is verified against the bot's server-side log
instead (see README for the exact log lines to check).

Prerequisites:
  - The bot is running: uv run python bot.py -t websocket
  - Test audio exists: uv run python scripts/generate_test_audio.py

Usage:
    uv run python scripts/voice_smoke_test_client.py
"""

import asyncio
import sys
import wave
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pipecat.frames.protobufs.frames_pb2 as frame_protos  # noqa: E402

WS_URL = "ws://localhost:7860/ws-client"
TEST_AUDIO_DIR = ROOT / "data" / "test_audio"
OUTPUT_DIR = ROOT / "data" / "test_audio" / "responses"
SAMPLE_RATE = 16000
CHUNK_MS = 20
CHUNK_BYTES = int(SAMPLE_RATE * (CHUNK_MS / 1000) * 2)  # 16-bit mono


def load_pcm(path: Path) -> bytes:
    with wave.open(str(path), "rb") as wav_file:
        assert wav_file.getframerate() == SAMPLE_RATE, "test audio must be 16kHz"
        assert wav_file.getnchannels() == 1, "test audio must be mono"
        return wav_file.readframes(wav_file.getnframes())


def save_pcm(path: Path, pcm: bytes, sample_rate: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm)


def make_audio_frame(pcm_chunk: bytes) -> bytes:
    frame = frame_protos.Frame()
    frame.audio.audio = pcm_chunk
    frame.audio.sample_rate = SAMPLE_RATE
    frame.audio.num_channels = 1
    return frame.SerializeToString()


async def send_audio(
    ws, pcm: bytes, real_time: bool = True, trailing_silence_secs: float = 0.0
) -> None:
    """Stream PCM to the bot, optionally followed by real silence frames.

    The trailing silence gives VAD an unambiguous utterance boundary: with no
    gap at all between two consecutive sends, back-to-back utterances can
    read as one continuous turn instead of two.
    """
    for offset in range(0, len(pcm), CHUNK_BYTES):
        chunk = pcm[offset : offset + CHUNK_BYTES]
        await ws.send(make_audio_frame(chunk))
        if real_time:
            await asyncio.sleep(CHUNK_MS / 1000)

    silence_chunk = b"\x00" * CHUNK_BYTES
    for _ in range(int(trailing_silence_secs * 1000 / CHUNK_MS)):
        await ws.send(make_audio_frame(silence_chunk))
        if real_time:
            await asyncio.sleep(CHUNK_MS / 1000)


class ReceivedTurn:
    def __init__(self):
        self.transcripts: list[str] = []
        self.audio_bytes = 0
        self.audio_chunks: list[bytes] = []
        self.text: list[str] = []


async def collect_for(
    ws, max_seconds: float, turn: ReceivedTurn, idle_seconds: float = 3.0
) -> None:
    """Collect frames until the stream goes quiet for ``idle_seconds`` (the
    turn has finished) or ``max_seconds`` total elapses (safety cap).

    A fixed wait-then-stop timeout would either cut a slow local-model
    response short or force every call site to block for the full window
    even when nothing more is coming (e.g. the STT-failover probe turn,
    which never produces a transcript). Idling out per read avoids both.
    """
    loop = asyncio.get_event_loop()
    deadline = loop.time() + max_seconds
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=min(idle_seconds, remaining))
        except asyncio.TimeoutError:
            return

        proto = frame_protos.Frame.FromString(raw)
        which = proto.WhichOneof("frame")
        if which == "transcription":
            turn.transcripts.append(proto.transcription.text)
            print(f"  [transcript] {proto.transcription.text!r}")
        elif which == "text":
            turn.text.append(proto.text.text)
            print(f"  [text]       {proto.text.text!r}")
        elif which == "audio":
            turn.audio_bytes += len(proto.audio.audio)
            turn.audio_chunks.append(proto.audio.audio)


async def run_round_trip_test(ws) -> None:
    """Audio round trip on the very first turn of a fresh connection.

    No GROQ_API_KEY is configured in this environment, so this same turn
    also exercises the STT failover: the pipeline's aggregator holds the
    turn open (it only closes once it has real transcribed text) while
    Groq fails and the ServiceSwitcher moves to the local Whisper fallback,
    so the one utterance below ends up proving both the failover and the
    round trip in a single exchange.
    """
    print("\n=== Test 1: audio round trip, exercising the Groq -> Whisper STT failover ===")
    # A longer utterance than hello.wav on purpose: Groq fails almost
    # immediately (~0.25s), and refund.wav's ~8.75s gives the ServiceSwitcher
    # comfortable room to fail over to Whisper well before VAD detects the
    # end of speech, instead of racing the switch against a short utterance.
    pcm = load_pcm(TEST_AUDIO_DIR / "refund.wav")

    turn = ReceivedTurn()
    # idle_seconds is generous: this covers the Groq failure + failover, plus
    # local CPU Whisper inference for the fallback path, which can take
    # several seconds between "nothing received yet" checks.
    collector = asyncio.create_task(collect_for(ws, 60.0, turn, idle_seconds=10.0))
    await send_audio(ws, pcm, trailing_silence_secs=2.0)
    await collector

    assert turn.audio_bytes > 0, "expected spoken audio back from the bot"

    out_path = OUTPUT_DIR / "refund_response.wav"
    save_pcm(out_path, b"".join(turn.audio_chunks), sample_rate=24000)
    print(f"PASS: {turn.audio_bytes} bytes of spoken audio came back")
    print(f"      saved response audio to {out_path}")
    print(
        "      NOTE: confirm the transcript itself against the bot's server log "
        "(grep for 'Transcription:') — it never crosses back over the transport."
    )


async def collect_until_first_audio(ws, turn: ReceivedTurn, max_seconds: float) -> bool:
    """Collect frames until the bot's spoken response starts, or time out.

    Used to find the real moment to barge in: with a segmented (non-streaming)
    STT, the bot doesn't start responding until well after the caller's audio
    finishes, transcribes, and generates a reply, so a fixed short timeout
    can't reliably land while the bot is actually speaking.
    """
    loop = asyncio.get_event_loop()
    deadline = loop.time() + max_seconds
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return False
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        except asyncio.TimeoutError:
            return False

        proto = frame_protos.Frame.FromString(raw)
        which = proto.WhichOneof("frame")
        if which == "transcription":
            turn.transcripts.append(proto.transcription.text)
            print(f"  [transcript] {proto.transcription.text!r}")
        elif which == "text":
            turn.text.append(proto.text.text)
            print(f"  [text]       {proto.text.text!r}")
        elif which == "audio":
            turn.audio_bytes += len(proto.audio.audio)
            turn.audio_chunks.append(proto.audio.audio)
            return True


async def run_interruption_test(ws) -> None:
    print("\n=== Test 2: interruption (barge in while refund.wav response is playing) ===")
    refund_pcm = load_pcm(TEST_AUDIO_DIR / "refund.wav")
    hello_pcm = load_pcm(TEST_AUDIO_DIR / "hello.wav")

    turn = ReceivedTurn()
    send_task = asyncio.create_task(
        send_audio(ws, refund_pcm, trailing_silence_secs=2.0)
    )
    started_speaking = await collect_until_first_audio(ws, turn, max_seconds=60.0)
    await send_task

    assert started_speaking, "bot never started speaking in response to refund.wav"
    first_turn_audio_bytes = turn.audio_bytes
    print(f"  bot started speaking: {first_turn_audio_bytes} bytes of audio so far")

    print("  barging in with hello.wav while the bot is still speaking...")
    turn2 = ReceivedTurn()
    collector2 = asyncio.create_task(collect_for(ws, 30.0, turn2, idle_seconds=10.0))
    await send_audio(ws, hello_pcm, trailing_silence_secs=2.0)
    await collector2

    assert turn2.audio_bytes > 0, "expected a fresh spoken response after the interruption"

    print(
        f"PASS: bot accepted the barge-in and responded with "
        f"{turn2.audio_bytes} bytes of new audio"
    )
    print(
        "      NOTE: confirm the interrupting transcript against the bot's "
        "server log (grep for 'Transcription:') — it never crosses back over "
        "the transport."
    )


async def main() -> None:
    async with websockets.connect(WS_URL) as ws:
        print(f"Connected to {WS_URL}")
        await run_round_trip_test(ws)
        await run_interruption_test(ws)
    print("\nAll smoke tests passed.")


if __name__ == "__main__":
    asyncio.run(main())

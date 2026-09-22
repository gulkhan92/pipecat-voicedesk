# AI Voice Agent for Customer Support (Pipecat)
## End-to-End Development Plan

Domain: E-commerce and Retail Customer Support
Core framework: Pipecat, https://github.com/pipecat-ai/pipecat

---

## 1. Project Overview

This project delivers a real-time, low-latency voice agent for e-commerce customer support, built on Pipecat, the open-source Python framework for voice and multimodal conversational agents. The agent runs as a continuous, streaming pipeline rather than a request-response loop: audio comes in over a browser-based real-time transport, passes through voice activity detection, is transcribed to text, is answered by a retrieval-augmented language model layer that reuses the same knowledge base and provider-switching logic as the text chatbot, and the answer is converted back to speech and streamed to the caller with minimal delay. Every component in the pipeline, speech-to-text, the language model, text-to-speech, and the transport layer, is a swappable Pipecat service, which is what makes it possible to keep the entire stack on free and open-source components while retaining a clear upgrade path to paid, higher-quality services later without rewriting the agent. The result is a voice experience that feels like talking to a real support line: the caller speaks naturally, can interrupt the agent mid-sentence, and receives a spoken, grounded answer drawn from the same customer support knowledge base used by the chat product.

## 2. Problem Statement

Phone and voice-based customer support is normally the most expensive channel for a retail business to staff, and building a real-time voice agent from scratch is difficult because it requires stitching together audio capture, voice activity detection, streaming speech-to-text, language model orchestration, streaming text-to-speech, and interruption handling, all with tight latency budgets, which most small teams do not have the time or infrastructure budget to build correctly. This project solves that by using Pipecat as the orchestration layer, since it already provides the pipeline abstraction, the streaming transport, the built-in voice activity detector, and a uniform interface to dozens of speech and language model providers, so the engineering effort goes into wiring free-tier and open-source services together and grounding the conversation in real support content, rather than into building low-level real-time audio plumbing. The agent must remain usable at zero infrastructure cost during development and demo, must degrade gracefully when a free-tier provider is rate-limited, and must sound and behave like a professional support line rather than a proof-of-concept script.

## 3. Dataset

The voice agent grounds its answers in the same support knowledge base used by the text chatbot, so voice and chat give consistent answers to the same question.

Dataset: Bitext Customer Service Tagged Training Dataset for LLM-based Chatbots
Source: Hugging Face, `bitext/Bitext-customer-support-llm-chatbot-training-dataset`
Content: roughly 26,000 to 27,000 `instruction`/`response` pairs across 27 customer service intents (orders, refunds, shipping, billing, account management, and similar categories).

Download:
```bash
pip install datasets
python - <<'PY'
from datasets import load_dataset
ds = load_dataset("bitext/Bitext-customer-support-llm-chatbot-training-dataset")
ds["train"].to_csv("data/raw/support_kb.csv", index=False)
PY
```

Usage: embed each `response` with the same open-source Hugging Face embedding model used elsewhere in the platform, store the vectors in PostgreSQL with pgvector, and retrieve the top matches for each transcribed query before generating a spoken answer. If this voice agent is built as a standalone project rather than as an extension of the wider support platform, reuse this same ingestion approach and folder layout:
```
data/
  raw/support_kb.csv
  processed/support_kb_cleaned.parquet
  embeddings/support_kb_embeddings.parquet
  scripts/load_support_kb.py
  scripts/generate_embeddings.py
```

## 4. Tech Stack (all free to use)

| Layer | Choice |
|---|---|
| Voice agent framework | Pipecat (`pipecat-ai`), BSD-2-Clause license |
| Language | Python 3.12 |
| Package management | `uv` |
| Real-time transport | Pipecat SmallWebRTCTransport for browser calls, or Pipecat WebSocket Server transport as a simpler fallback |
| Voice activity detection | Silero VAD, built into Pipecat |
| Speech to text | Pipecat's Groq (Whisper) STT service on the Groq free tier, with local `faster-whisper` as an offline fallback that needs no API key |
| Language model | Same two-provider setup as the rest of the platform: Groq (`openai/gpt-oss-20b`) as primary, Gemini (`gemini-2.5-flash`) as fallback, both available as native Pipecat LLM services |
| Text to speech | Piper or Kokoro, both open-source, local, no API key required; Pipecat's Groq TTS service as a free-tier hosted alternative |
| Structured conversation logic | Pipecat Flows for defining the support conversation as explicit states (greeting, intent capture, resolution, escalation, closing) |
| Retrieval | PostgreSQL with pgvector, same schema as the text chatbot |
| Embeddings | `BAAI/bge-small-en-v1.5` or `sentence-transformers/all-MiniLM-L6-v2`, run locally |
| Backend integration | FastAPI service exposing the call session endpoint that the browser client connects to, shared with the rest of the platform where applicable |
| Client | Pipecat's JavaScript or React client SDK, embedded in the same React frontend as the chat and dashboard product |
| Observability | OpenTelemetry export, supported natively by Pipecat, for pipeline latency and turn-by-turn tracing |
| Debugging during development | Whisker, Pipecat's real-time pipeline debugger |
| Containerization and hosting | Docker, Docker Compose; free tier of Render or Railway for the backend process |

Rate limits on Groq's free tier for both the STT and LLM services change over time; verify current values in the Groq console before relying on them, and confirm the fallback path is exercised in testing rather than assumed.

## 5. Pipeline Architecture

```
Browser client (Pipecat JS/React SDK, microphone capture)
        |
        v  WebRTC or WebSocket, real-time audio
Pipecat pipeline (single Python process)
  1. Transport input (SmallWebRTCTransport / WebSocket Server)
  2. Silero VAD (detects speech start and end, enables interruption)
  3. STT service (Groq Whisper, fallback faster-whisper local)
  4. Context aggregator (rolling conversation history)
  5. Retrieval step (embed transcript, pgvector similarity search against support_kb)
  6. LLM service (Groq gpt-oss-20b primary, Gemini 2.5 Flash fallback)
  7. Pipecat Flows state manager (tracks where the caller is in the support flow)
  8. TTS service (Piper / Kokoro local, or Groq TTS hosted)
  9. Transport output (streamed audio back to the client)
        |
        v
PostgreSQL + pgvector (support_kb, call transcripts, call metadata)
```

## 6. Phase-Wise Development Plan

### Phase 0: Environment Setup

- Install `uv`, then install the Pipecat CLI with `uv tool install "pipecat-ai[cli]"`.
- Scaffold the project with `pipecat init` and select the web/mobile bot template as the starting point, or create the project manually with `uv init` followed by `uv add pipecat-ai`.
- Add only the extras actually needed to keep the install lightweight, for example `uv add "pipecat-ai[groq,silero]"` plus whatever local TTS package is chosen.
- Copy `env.example` to `.env` and define `GROQ_API_KEY`, `GEMINI_API_KEY`, the database URL, and any transport-specific configuration.
- Set up the same PostgreSQL with pgvector instance used by the rest of the platform (or a standalone instance via Docker Compose if this is a separate project), and confirm connectivity from the Python process.
- Install development dependencies and pre-commit hooks as documented in Pipecat's contributing guide, and set up pytest for the project's own test suite.

### Phase 1: Knowledge Base Ingestion

- Run the dataset download and cleaning scripts from section 3 to populate `support_kb` in PostgreSQL.
- Generate and store embeddings for every row using the chosen Hugging Face model, with an HNSW or IVFFlat index on the vector column for fast lookups.
- Write a small retrieval module independent of Pipecat, exposing a single function that takes a text query and returns the top-k matching support entries with similarity scores, so it can be called as a plain step inside the pipeline in Phase 4.

### Phase 2: Minimal Voice Pipeline (Text-Free Smoke Test)

- Build the smallest possible Pipecat pipeline first: transport input, Silero VAD, STT, a placeholder LLM step that echoes the transcript, TTS, transport output.
- Run this locally using the WebSocket Server transport and a simple test client to confirm audio round-trips correctly and latency is acceptable before adding any business logic.
- Confirm interruption handling works out of the box, meaning the agent stops speaking when the caller starts talking.

### Phase 3: Speech-to-Text and Text-to-Speech Configuration

- Wire in the Groq Whisper STT service as the primary transcription service, and confirm streaming partial transcripts appear correctly.
- Add `faster-whisper` as a local fallback service, and add a simple health check that switches to it if the Groq STT service errors out or is rate-limited.
- Wire in Piper or Kokoro as the primary TTS service since both run fully locally with no API key and no rate limit.
- Tune voice, sample rate, and audio format settings for natural-sounding output, and confirm the audio streams smoothly back to the client without gaps.

### Phase 4: LLM Provider Layer and Retrieval Integration

- Build a `ProviderRouter` exactly as used in the text chatbot: Groq `openai/gpt-oss-20b` as primary, Gemini `gemini-2.5-flash` as fallback, with quota tracking in Redis and automatic switching on rate limit errors, so the two channels behave identically and share the same reliability guarantees.
- Insert the retrieval module from Phase 1 as a step before the LLM call: take the finalized transcript for a turn, run the similarity search, and inject only the top 2 to 3 matching knowledge base entries into a compact system prompt.
- Keep the conversation context aggregator trimmed to the last few turns, since voice conversations are turn-heavy and unbounded context directly increases both latency and token usage.
- Cap `max_tokens` tightly, since voice responses should be short and conversational rather than long written answers; a long LLM response also directly increases time-to-first-audio.
- Log the provider used, tokens used, and retrieval hits for every turn to the database for later analysis on the analytics dashboard.

### Phase 5: Conversation Flow Design with Pipecat Flows

- Model the support call as an explicit state machine using Pipecat Flows: greeting and identity capture, intent capture, knowledge base grounded resolution, clarification loop if the answer is not confident, escalation path if the query cannot be resolved, and a closing state.
- Define exit conditions for each state so the agent does not loop indefinitely on unclear input, and define a maximum number of clarification attempts before offering escalation.
- Write the escalation state to log a structured summary of the call (not a raw transcript dump) that a human agent could act on later.

### Phase 6: Transport and Client Integration

- Move from the WebSocket Server transport used in early development to SmallWebRTCTransport for lower latency in the browser, or keep the WebSocket transport if it is sufficient for the target scale.
- Integrate Pipecat's JavaScript or React client SDK into the same React frontend used by the rest of the platform, adding a voice call interface with a call start and end control, a live transcript display, and a visual speaking indicator.
- Handle reconnect and error states gracefully in the client so a dropped network connection does not require a full page reload.

### Phase 7: Observability and Debugging

- Enable OpenTelemetry export from the pipeline and capture per-turn latency broken down by STT time, retrieval time, LLM time, and TTS time, so slow segments can be identified and optimized.
- Use Whisker during development to inspect the live pipeline and step through processor behavior when debugging unexpected agent responses.
- Add structured logging for every call session (start time, end time, turn count, provider used per turn, escalation outcome) into the same database used by the analytics dashboard, so voice agent performance can be reported alongside chat performance.

### Phase 8: Security and Reliability

- Authenticate the client connection to the voice pipeline using the same JWT-based authentication used elsewhere in the platform, so anonymous callers cannot open arbitrary pipeline sessions against the backend.
- Rate limit new call sessions per user and per IP address to protect the free-tier STT and LLM quotas from being exhausted by a single source.
- Add a hard maximum call duration and a maximum idle-silence timeout that ends the session cleanly.
- Store only the structured call summary and metadata by default, and make full transcript storage an explicit, documented, opt-in setting, since spoken conversations can include sensitive personal information.
- Add automatic retry and provider fallback tests: simulate a rate-limited Groq response and confirm the pipeline continues the call using Gemini without the caller noticing an interruption.

### Phase 9: Testing

- Unit test the provider router, the retrieval module, and the Pipecat Flows state transitions independently of the audio pipeline.
- Integration test the full pipeline using Pipecat's testing utilities and a scripted audio input, verifying the correct final transcript, retrieval hit, and synthesized response for a set of representative support questions drawn from the dataset's intent categories.
- Manually test interruption handling, escalation triggering, and provider fallback with real spoken input before considering the agent demo-ready.

### Phase 10: Deployment

- Containerize the Pipecat process with a production Dockerfile.
- Deploy the backend process to a free tier of Render or Railway, confirming the chosen transport works correctly behind the platform's networking (WebRTC in particular may need specific port or TURN configuration, documented in Pipecat's deployment guide).
- Deploy the React client alongside the rest of the platform's frontend, pointed at the deployed voice agent endpoint.
- Set up a GitHub Actions workflow that runs the test suite on every pull request before merging.

## 7. Documentation Requirements

Include a dedicated `README.md` covering: a one-paragraph summary of the voice agent, the full pipeline diagram from section 5, prerequisites and local setup steps including the Pipecat CLI installation, how to configure both LLM provider API keys and confirm the fallback behavior, how to run the dataset ingestion scripts, how to start a local call and test it end to end, how conversation state and escalation are handled, known latency characteristics per pipeline stage, deployment instructions including any transport-specific networking notes, and licensing information for Pipecat itself and for the Bitext dataset. Write the documentation in clear, professional language throughout, with no casual or unprofessional wording anywhere in the repository, and no em dash characters used anywhere in any file.

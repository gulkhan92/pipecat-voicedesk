# VoiceDesk client

Browser voice-call widget for the support agent, built on Pipecat's
JavaScript client SDK (`@pipecat-ai/client-js`) over `SmallWebRTCTransport`.

## Setup

```bash
cd client
npm install
cp env.example .env
```

Edit `.env` if the bot server isn't running at the default
`http://localhost:7860`. Set `VITE_AUTH_TOKEN` only if the server has
`REQUIRE_AUTH=true` (get one with `uv run python scripts/issue_dev_token.py`
from the project root).

## Run

Start the bot server first (from the project root):

```bash
uv run bot.py
```

Then, in `client/`:

```bash
npm run dev
```

Open the printed local URL (typically `http://localhost:5173`). Click
**Start call**, allow microphone access, and talk.

## What's in the widget

- **Call control**: a single button toggles Start call / End call.
- **Speaking indicator**: a pulsing dot shows who's talking right now,
  you, the agent, or neither (listening).
- **Live transcript**: the caller's and agent's turns appear as they're
  spoken, via the RTVI `onUserTranscript` / `onBotTranscript` events.
- **Reconnect handling**: if the connection drops unexpectedly (not from
  clicking End call), a banner offers a one-click reconnect, with no page
  reload needed. The transcript so far is preserved.

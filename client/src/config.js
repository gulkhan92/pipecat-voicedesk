/**
 * Client configuration for the VoiceDesk support call widget.
 *
 * Phase 6 uses SmallWebRTCTransport exclusively (lower latency than the
 * WebSocket transport used in early development, kept server-side only for
 * the scripted smoke-test client).
 */

export const PROJECT_NAME = 'VoiceDesk Support';

const botStartUrl = import.meta.env.VITE_BOT_START_URL || 'http://localhost:7860/start';

if (!import.meta.env.VITE_BOT_START_URL) {
  console.warn(`VITE_BOT_START_URL not configured, using default: ${botStartUrl}`);
}

// Phase 8: only used when the server has REQUIRE_AUTH=true. In the full
// platform this comes from the existing login session, not an env var; see
// scripts/issue_dev_token.py for a local stand-in while testing.
const authToken = import.meta.env.VITE_AUTH_TOKEN || null;

export const WEBRTC_CONNECT_PARAMS = {
  endpoint: botStartUrl,
  requestData: {
    createDailyRoom: false,
    enableDefaultIceServers: true,
    transport: 'webrtc',
    ...(authToken ? { token: authToken } : {}),
  },
};

export async function createWebRTCTransport() {
  const { SmallWebRTCTransport } = await import('@pipecat-ai/small-webrtc-transport');
  return new SmallWebRTCTransport();
}

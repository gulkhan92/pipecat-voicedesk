import { PipecatClient, RTVIEvent } from '@pipecat-ai/client-js';
import { WEBRTC_CONNECT_PARAMS, createWebRTCTransport } from './config';

/**
 * VoiceDesk support call widget.
 *
 * Call start/end button, a live transcript, and a visual speaking indicator
 * (who's talking right now: the caller or the agent). A dropped connection
 * shows a "Reconnect" banner instead of requiring a full page reload: the
 * client is torn down and a fresh one built on reconnect, but the page
 * itself, and everything already in the transcript, stays put.
 */
class VoiceCallWidget {
  constructor() {
    this.client = null;
    this.callActive = false;
    // Distinguishes a disconnect the user asked for (End call) from one the
    // network caused, so only the latter shows the reconnect banner.
    this.userInitiatedDisconnect = false;

    this.callBtn = document.getElementById('call-btn');
    this.statusBadge = document.getElementById('status-badge');
    this.speakingDot = document.getElementById('speaking-dot');
    this.speakingLabel = document.getElementById('speaking-label');
    this.transcriptLog = document.getElementById('transcript-log');
    this.reconnectBanner = document.getElementById('reconnect-banner');
    this.reconnectBtn = document.getElementById('reconnect-btn');
    this.errorBanner = document.getElementById('error-banner');

    this.callBtn.addEventListener('click', () => this.onCallButtonClick());
    this.reconnectBtn.addEventListener('click', () => this.reconnect());
  }

  onCallButtonClick() {
    if (this.callActive) {
      this.endCall();
    } else {
      this.startCall();
    }
  }

  async startCall() {
    this.hideError();
    this.hideReconnectBanner();
    this.userInitiatedDisconnect = false;
    this.setStatus('connecting', 'Connecting…');
    this.callBtn.disabled = true;

    try {
      const transport = await createWebRTCTransport();

      this.client = new PipecatClient({
        transport,
        enableMic: true,
        enableCam: false,
        callbacks: {
          onConnected: () => this.onConnected(),
          onDisconnected: () => this.onDisconnected(),
          onTransportStateChanged: (state) => this.onTransportStateChanged(state),
          onUserStartedSpeaking: () => this.setSpeaking('user'),
          onUserStoppedSpeaking: () => this.setSpeaking('none'),
          onBotStartedSpeaking: () => this.setSpeaking('bot'),
          onBotStoppedSpeaking: () => this.setSpeaking('none'),
          onUserTranscript: (data) => {
            if (data.final) this.addTranscriptEntry(data.text, 'user');
          },
          onBotTranscript: (data) => this.addTranscriptEntry(data.text, 'bot'),
          onError: (error) => this.showError(error?.message || 'Connection error'),
        },
      });

      this.attachBotAudio();

      await this.client.startBotAndConnect(WEBRTC_CONNECT_PARAMS);
    } catch (error) {
      console.error('Failed to start call:', error);
      this.showError(error?.message || 'Failed to start the call');
      this.setStatus('idle', 'Not connected');
      this.callBtn.disabled = false;
    }
  }

  async endCall() {
    this.userInitiatedDisconnect = true;
    this.callBtn.disabled = true;
    if (this.client) {
      await this.client.disconnect();
    }
  }

  async reconnect() {
    this.hideReconnectBanner();
    await this.startCall();
  }

  attachBotAudio() {
    this.client.on(RTVIEvent.TrackStarted, (track, participant) => {
      if (!participant?.local && track.kind === 'audio') {
        const audio = document.createElement('audio');
        audio.autoplay = true;
        audio.srcObject = new MediaStream([track]);
        document.body.appendChild(audio);
        this._botAudioEl = audio;
      }
    });
  }

  onConnected() {
    this.callActive = true;
    this.callBtn.textContent = 'End call';
    this.callBtn.classList.add('call-btn-end');
    this.callBtn.classList.remove('call-btn-start');
    this.callBtn.disabled = false;
    this.setStatus('connected', 'Connected');
    this.setSpeaking('none');

    const placeholder = this.transcriptLog.querySelector('.placeholder');
    if (placeholder) placeholder.remove();
  }

  onDisconnected() {
    this.callActive = false;
    this.callBtn.textContent = 'Start call';
    this.callBtn.classList.add('call-btn-start');
    this.callBtn.classList.remove('call-btn-end');
    this.callBtn.disabled = false;
    this.setSpeaking('disconnected');

    if (this._botAudioEl) {
      this._botAudioEl.remove();
      this._botAudioEl = null;
    }

    if (this.userInitiatedDisconnect) {
      this.setStatus('idle', 'Not connected');
    } else {
      // The connection dropped on its own (network blip, server restart,
      // etc.), offer a one-click reconnect instead of asking for a reload.
      this.setStatus('error', 'Disconnected');
      this.showReconnectBanner();
    }

    this.client = null;
  }

  onTransportStateChanged(state) {
    if (state === 'error' && this.callActive) {
      this.setStatus('error', 'Connection error');
    }
  }

  setStatus(kind, label) {
    this.statusBadge.textContent = label;
    this.statusBadge.className = `status-badge status-${kind}`;
  }

  setSpeaking(who) {
    this.speakingDot.className = 'speaking-dot';
    if (who === 'user') {
      this.speakingDot.classList.add('speaking-dot-user');
      this.speakingLabel.textContent = "You're speaking";
    } else if (who === 'bot') {
      this.speakingDot.classList.add('speaking-dot-bot');
      this.speakingLabel.textContent = 'Agent speaking…';
    } else if (who === 'disconnected') {
      this.speakingLabel.textContent = 'Not connected';
    } else {
      this.speakingDot.classList.add('speaking-dot-listening');
      this.speakingLabel.textContent = 'Listening…';
    }
  }

  addTranscriptEntry(text, role) {
    if (!text) return;
    const entry = document.createElement('div');
    entry.className = `transcript-entry ${role}`;

    const roleLabel = document.createElement('div');
    roleLabel.className = 'role';
    roleLabel.textContent = role === 'user' ? 'You' : 'Agent';

    const body = document.createElement('div');
    body.textContent = text;

    entry.appendChild(roleLabel);
    entry.appendChild(body);
    this.transcriptLog.appendChild(entry);
    this.transcriptLog.scrollTop = this.transcriptLog.scrollHeight;
  }

  showReconnectBanner() {
    this.reconnectBanner.hidden = false;
  }

  hideReconnectBanner() {
    this.reconnectBanner.hidden = true;
  }

  showError(message) {
    this.errorBanner.textContent = message;
    this.errorBanner.hidden = false;
  }

  hideError() {
    this.errorBanner.hidden = true;
    this.errorBanner.textContent = '';
  }
}

window.addEventListener('DOMContentLoaded', () => {
  new VoiceCallWidget();
});

"""Phase 8: best-effort client IP extraction, for rate limiting new calls.

Reliable for the WebSocket transport (the runner hands us the raw
``WebSocket`` object). For WebRTC, aiortc's ``RTCPeerConnection`` doesn't
expose the remote address in a simple, stable way before ICE has completed,
so this falls back to "unknown" there; a production deployment fronted by a
reverse proxy should instead read a forwarded-for header at that proxy and
pass it through ``runner_args.body``.
"""

from pipecat.runner.types import RunnerArguments, WebSocketRunnerArguments


def get_client_ip(runner_args: RunnerArguments) -> str:
    if isinstance(runner_args, WebSocketRunnerArguments):
        client = getattr(runner_args.websocket, "client", None)
        if client and getattr(client, "host", None):
            return client.host

    if isinstance(runner_args.body, dict):
        forwarded = runner_args.body.get("client_ip")
        if forwarded:
            return str(forwarded)

    return "unknown"

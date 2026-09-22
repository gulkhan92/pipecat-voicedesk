"""Phase 7: shared per-session state, mirroring TurnState's pattern.

Populated as the call progresses (TurnLogger records each turn's provider,
CallFlow's escalation path marks the outcome) and written to call_sessions
once the call ends.
"""

from dataclasses import dataclass, field


@dataclass
class SessionState:
    session_id: int | None = None
    turn_count: int = 0
    providers_used: set[str] = field(default_factory=set)
    escalated: bool = False
    escalation_reason: str | None = None

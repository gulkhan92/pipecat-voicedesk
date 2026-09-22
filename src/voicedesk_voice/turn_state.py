"""Shared per-turn state passed between the retrieval injector, the turn
logger, and (from Phase 5) the call flow, since retrieval happens before the
LLM call and the frames that carry token usage / provider identity only
appear after it.
"""

from dataclasses import dataclass


@dataclass
class TurnState:
    transcript: str = ""
    retrieval_hit_count: int = 0
    retrieval_top_score: float | None = None
    # Phase 5: only the knowledge-base-grounded flow nodes (resolution,
    # clarification) want retrieval grounding injected; greeting, intent
    # capture, escalation, and closing do not. Set by the active flow node.
    retrieval_enabled: bool = True

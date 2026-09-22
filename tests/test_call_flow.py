"""Phase 9: unit tests for the Pipecat Flows state transitions, independent
of the audio pipeline. Mirrors the manual verification done in Phase 5, now
as regression tests.
"""

from unittest.mock import MagicMock

import pytest

from voicedesk_voice.call_flow import CallFlow
from voicedesk_voice.config import MAX_CLARIFICATION_ATTEMPTS
from voicedesk_voice.session_state import SessionState
from voicedesk_voice.turn_state import TurnState


class FakeFlowManager:
    """Stands in for pipecat_flows.FlowManager: only .state is used by the
    functions under test.
    """

    def __init__(self, **state):
        self.state = state


@pytest.fixture
def flow():
    return CallFlow(
        llm=None,
        context_aggregator=None,
        worker=MagicMock(),
        turn_state=TurnState(),
        session_state=SessionState(),
    )


def test_greeting_node_disables_retrieval(flow):
    node = flow.greeting_node()
    assert node["name"] == "greeting"
    assert flow._turn_state.retrieval_enabled is False
    assert node["functions"] == [flow.capture_identity]


async def test_capture_identity_moves_to_intent_node(flow):
    fm = FakeFlowManager()
    result, next_node = await flow.capture_identity(fm, name="Jordan")
    assert fm.state["caller_name"] == "Jordan"
    assert next_node["name"] == "intent_capture"
    assert flow._turn_state.retrieval_enabled is False


async def test_submit_intent_moves_to_resolution_and_enables_retrieval(flow):
    fm = FakeFlowManager()
    result, next_node = await flow.submit_intent(fm, summary="a damaged blender")
    assert fm.state["intent"] == "a damaged blender"
    assert fm.state["clarification_attempts"] == 0
    assert next_node["name"] == "resolution"
    assert flow._turn_state.retrieval_enabled is True


async def test_resolve_moves_to_closing(flow):
    fm = FakeFlowManager()
    result, next_node = await flow.resolve(fm, answer="You can return it within 30 days.")
    assert fm.state["resolution"] == "You can return it within 30 days."
    assert next_node["name"] == "closing"


async def test_need_clarification_loops_until_limit_then_escalates(flow, monkeypatch):
    logged = {}

    async def fake_log_escalation(**kwargs):
        logged.update(kwargs)
        return "structured summary"

    monkeypatch.setattr("voicedesk_voice.call_flow.log_escalation", fake_log_escalation)

    fm = FakeFlowManager(caller_name="Jordan", intent="a damaged blender", clarification_attempts=0)

    for i in range(MAX_CLARIFICATION_ATTEMPTS):
        result, next_node = await flow.need_clarification(fm, follow_up_question=f"q{i + 1}")
        assert next_node["name"] == "clarification"
        assert fm.state["clarification_attempts"] == i + 1

    # One more than the limit must escalate instead of looping again.
    result, next_node = await flow.need_clarification(fm, follow_up_question="one too many")
    assert next_node["name"] == "closing"
    assert result["escalated"] is True
    assert logged["reason"] == f"unresolved after {MAX_CLARIFICATION_ATTEMPTS} clarification attempts"
    assert logged["attempts"] == MAX_CLARIFICATION_ATTEMPTS + 1


async def test_request_escalation_logs_and_moves_to_closing(flow, monkeypatch):
    logged = {}

    async def fake_log_escalation(**kwargs):
        logged.update(kwargs)
        return "structured summary"

    monkeypatch.setattr("voicedesk_voice.call_flow.log_escalation", fake_log_escalation)

    fm = FakeFlowManager(caller_name="Jordan", intent="a billing dispute", clarification_attempts=0)
    result, next_node = await flow.request_escalation(fm, reason="needs a human for billing")

    assert next_node["name"] == "closing"
    assert result == {"escalated": True, "summary": "structured summary"}
    assert logged["reason"] == "needs a human for billing"
    assert flow._session_state.escalated is True
    assert flow._session_state.escalation_reason == "needs a human for billing"


async def test_provide_clarification_appends_to_intent_and_returns_to_resolution(flow):
    fm = FakeFlowManager(intent="a damaged blender")
    result, next_node = await flow.provide_clarification(fm, answer="order 12345")
    assert fm.state["intent"] == "a damaged blender (order 12345)"
    assert next_node["name"] == "resolution"
    assert flow._turn_state.retrieval_enabled is True


def test_closing_node_disables_retrieval(flow):
    flow._turn_state.retrieval_enabled = True
    node = flow.closing_node()
    assert node["name"] == "closing"
    assert node["functions"] == []
    assert flow._turn_state.retrieval_enabled is False

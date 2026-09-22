"""Phase 5: the support call as an explicit state machine, using Pipecat Flows.

States: greeting (identity capture) -> intent capture -> knowledge-base
grounded resolution -> clarification loop (bounded by
MAX_CLARIFICATION_ATTEMPTS) -> escalation or closing.

Each node function returns a ``(result, next_node)`` pair per the Flows
"consolidated function" pattern (see pipecat_flows.types.NodeConfig).
Retrieval grounding (RetrievalContextInjector) is toggled per node via
``TurnState.retrieval_enabled``; only resolution and clarification want it.

``CallFlow`` is instantiated fresh per call session (in bot.py) rather than
using module-level functions, so its per-node retrieval toggling and its
``FlowManager`` never leak state between two concurrent calls handled by the
same process.
"""

from pipecat.flows import ConsolidatedFunctionResult, FlowManager, NodeConfig

from voicedesk_voice.config import MAX_CLARIFICATION_ATTEMPTS
from voicedesk_voice.escalation_log import log_escalation
from voicedesk_voice.session_state import SessionState
from voicedesk_voice.turn_state import TurnState

ROLE_MESSAGE = (
    "You are a concise, professional customer support voice agent for an "
    "e-commerce retailer. Your responses are spoken aloud, so answer in one "
    "or two short, natural sentences with no formatting, bullet points, or "
    "emojis."
)


class CallFlow:
    """Builds this session's flow nodes and owns its FlowManager."""

    def __init__(
        self,
        *,
        llm,
        context_aggregator,
        worker,
        turn_state: TurnState,
        session_state: SessionState,
    ):
        self._turn_state = turn_state
        self._session_state = session_state
        self.manager = FlowManager(
            llm=llm,
            context_aggregator=context_aggregator,
            worker=worker,
        )

    async def start(self) -> None:
        """Enter the flow at the greeting node."""
        await self.manager.initialize(self.greeting_node())

    def _set_retrieval(self, enabled: bool) -> None:
        self._turn_state.retrieval_enabled = enabled

    # -- Greeting / identity capture -----------------------------------

    def greeting_node(self) -> NodeConfig:
        self._set_retrieval(False)
        return {
            "name": "greeting",
            "role_message": ROLE_MESSAGE,
            "task_messages": [
                {
                    "role": "system",
                    "content": (
                        "Greet the caller warmly and ask for their name. "
                        "Once they tell you, call capture_identity with it. "
                        "If they decline or it's unclear after one "
                        "follow-up, call capture_identity with name set to "
                        "null."
                    ),
                }
            ],
            "functions": [self.capture_identity],
        }

    async def capture_identity(
        self, flow_manager: FlowManager, name: str | None = None
    ) -> ConsolidatedFunctionResult:
        """Record the caller's name, or that they declined to give one.

        Args:
            name: The caller's name as they gave it, or null if they
                declined or it stayed unclear after a follow-up.
        """
        flow_manager.state["caller_name"] = name
        return {"acknowledged": True}, self.intent_node()

    # -- Intent capture ---------------------------------------------------

    def intent_node(self) -> NodeConfig:
        self._set_retrieval(False)
        return {
            "name": "intent_capture",
            "task_messages": [
                {
                    "role": "system",
                    "content": (
                        "Ask the caller what they need help with today. "
                        "Once you understand their question, call "
                        "submit_intent with a concise one-sentence summary "
                        "of it."
                    ),
                }
            ],
            "functions": [self.submit_intent],
        }

    async def submit_intent(
        self, flow_manager: FlowManager, summary: str
    ) -> ConsolidatedFunctionResult:
        """Record a concise summary of what the caller needs help with.

        Args:
            summary: A one-sentence summary of the caller's question or issue.
        """
        flow_manager.state["intent"] = summary
        flow_manager.state["clarification_attempts"] = 0
        return {"acknowledged": True}, self.resolution_node()

    # -- Knowledge-base grounded resolution --------------------------------

    def resolution_node(self) -> NodeConfig:
        self._set_retrieval(True)
        return {
            "name": "resolution",
            "task_messages": [
                {
                    "role": "system",
                    "content": (
                        "Using only the support information you've been "
                        "given, try to answer the caller's question in one "
                        "or two short sentences. If it fully answers their "
                        "question, call resolve with your answer. If the "
                        "support information doesn't cover it or you're not "
                        "confident, call need_clarification with a short "
                        "follow-up question instead of guessing. If the "
                        "caller's issue clearly needs a human (e.g. a "
                        "billing dispute, an account security issue), call "
                        "request_escalation instead."
                    ),
                }
            ],
            "functions": [self.resolve, self.need_clarification, self.request_escalation],
        }

    async def resolve(self, flow_manager: FlowManager, answer: str) -> ConsolidatedFunctionResult:
        """Record the answer given to the caller once their question is resolved.

        Args:
            answer: The answer you gave the caller.
        """
        flow_manager.state["resolution"] = answer
        return {"acknowledged": True}, self.closing_node()

    async def need_clarification(
        self, flow_manager: FlowManager, follow_up_question: str
    ) -> ConsolidatedFunctionResult:
        """Ask the caller a clarifying follow-up question instead of guessing.

        Args:
            follow_up_question: The clarifying question to ask the caller.
        """
        attempts = flow_manager.state.get("clarification_attempts", 0) + 1
        flow_manager.state["clarification_attempts"] = attempts

        if attempts > MAX_CLARIFICATION_ATTEMPTS:
            summary = await self._escalate(
                flow_manager,
                reason=f"unresolved after {MAX_CLARIFICATION_ATTEMPTS} clarification attempts",
            )
            return {"escalated": True, "summary": summary}, self.closing_node()

        return {"acknowledged": True}, self.clarification_node(follow_up_question)

    async def request_escalation(
        self, flow_manager: FlowManager, reason: str
    ) -> ConsolidatedFunctionResult:
        """Escalate the call to a human agent instead of answering it yourself.

        Args:
            reason: A short reason this call needs a human agent.
        """
        summary = await self._escalate(flow_manager, reason=reason)
        return {"escalated": True, "summary": summary}, self.closing_node()

    async def _escalate(self, flow_manager: FlowManager, *, reason: str) -> str:
        self._session_state.escalated = True
        self._session_state.escalation_reason = reason
        return await log_escalation(
            session_id=self._session_state.session_id,
            caller_name=flow_manager.state.get("caller_name"),
            intent=flow_manager.state.get("intent"),
            reason=reason,
            attempts=flow_manager.state.get("clarification_attempts", 0),
        )

    # -- Clarification loop -------------------------------------------------

    def clarification_node(self, follow_up_question: str) -> NodeConfig:
        self._set_retrieval(True)
        return {
            "name": "clarification",
            "task_messages": [
                {
                    "role": "system",
                    "content": (
                        "Ask the caller this clarifying question, in your "
                        f"own words: {follow_up_question!r}. Once they "
                        "answer, call provide_clarification with what they "
                        "said."
                    ),
                }
            ],
            "functions": [self.provide_clarification],
        }

    async def provide_clarification(
        self, flow_manager: FlowManager, answer: str
    ) -> ConsolidatedFunctionResult:
        """Record the caller's answer to the clarifying question.

        Args:
            answer: What the caller said in response to the clarifying
                question.
        """
        intent = flow_manager.state.get("intent", "")
        flow_manager.state["intent"] = f"{intent} ({answer})" if intent else answer
        return {"acknowledged": True}, self.resolution_node()

    # -- Closing --------------------------------------------------------

    def closing_node(self) -> NodeConfig:
        self._set_retrieval(False)
        return {
            "name": "closing",
            "task_messages": [
                {
                    "role": "system",
                    "content": (
                        "If the caller's question was resolved, thank them "
                        "and say a brief goodbye. If they were escalated, "
                        "let them know a human agent will follow up, then "
                        "say goodbye. Keep it to one short sentence."
                    ),
                }
            ],
            "functions": [],
        }

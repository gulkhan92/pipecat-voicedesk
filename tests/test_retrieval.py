import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from voicedesk_retrieval.retrieval import SupportKBHit  # noqa: E402


def test_support_kb_hit_is_immutable_and_typed():
    hit = SupportKBHit(
        id=1,
        intent="refund",
        instruction="How do I get a refund?",
        response="You can request a refund from your order history.",
        similarity=0.87,
    )

    assert hit.id == 1
    assert hit.intent == "refund"
    assert 0.0 <= hit.similarity <= 1.0

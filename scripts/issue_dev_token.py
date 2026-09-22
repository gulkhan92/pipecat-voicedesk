"""Phase 8 dev helper: issue a JWT for testing REQUIRE_AUTH=true locally.

In the full platform, token issuance belongs to the existing login
endpoint; this script stands in for that so the auth path can be exercised
without one.

Usage:
    uv run python scripts/issue_dev_token.py [subject]
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from voicedesk_voice.auth import issue_token  # noqa: E402


def main() -> None:
    subject = sys.argv[1] if len(sys.argv) > 1 else "dev-user"
    token = issue_token(subject)
    print(token)


if __name__ == "__main__":
    main()

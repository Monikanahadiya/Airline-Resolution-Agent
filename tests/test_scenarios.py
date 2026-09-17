"""
tests/test_scenarios.py

Runs the 3 required scenarios from the assignment against your actual agent
(agent/agent.py) and checks the outcomes against what's expected —
cross-referenced from data/policy_data.json's `test_scenarios` block.

NOTE: this makes real calls to the Claude API (costs a small amount of
credit) since it's testing the live agent, not a mock.

Run:
    export ANTHROPIC_API_KEY=your_key_here
    python tests/test_scenarios.py

What this DOES check automatically: whether the `escalated` flag matches
what should happen for each turn.
What this DOES NOT fully check: whether the reply text is worded well, or
whether it correctly offers rebook-vs-refund as a real choice — that's
inherently a judgment call on natural language, so read the printed replies
yourself and eyeball them against the expected behavior shown.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent / "agent"))
from agent import handle_message  # noqa: E402

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
WARN = "\033[93mCHECK MANUALLY\033[0m"


def run_case(label, pnr, turns, expect_escalated_on_turn):
    """
    turns: list of customer messages to send in order (same PNR = same
    conversation thread, since agent.py keeps history per PNR).
    expect_escalated_on_turn: dict {turn_index: bool} for turns worth
    checking automatically.
    """
    print(f"\n{'=' * 60}\n{label}  (PNR: {pnr})\n{'=' * 60}")
    for i, message in enumerate(turns):
        print(f"\n> Customer: {message}")
        result = handle_message(pnr, message)
        print(f"< Agent: {result['reply']}")
        print(f"  escalated={result['escalated']}")

        if i in expect_escalated_on_turn:
            expected = expect_escalated_on_turn[i]
            status = PASS if result["escalated"] == expected else FAIL
            print(f"  [{status}] expected escalated={expected}")
        else:
            print(f"  [{WARN}] read the reply above against the expected behavior")


def main():
    # Scenario 1 — Priya Nair: cancellation, then an out-of-policy demand
    run_case(
        "Scenario 1: Priya Nair — cancellation + out-of-policy upgrade demand",
        "SK4821X",
        turns=[
            "Hi, I heard my flight SK-204 to Goa got cancelled. What are my options?",
            "This is so frustrating, I'm furious. I want a full cash refund AND a free upgrade to business class on my return flight for the trouble.",
        ],
        expect_escalated_on_turn={1: True},  # turn 0 is a normal in-policy question
    )

    # Scenario 2 — Arvind Kulkarni: 4h delay, asks for hotel (should be denied, not escalated)
    run_case(
        "Scenario 2: Arvind Kulkarni — 4h delay, asks for hotel",
        "TR1190B",
        turns=[
            "My flight SK-118 got delayed and I'm going to miss my connecting meeting. Since it's been such a long delay, can I get hotel accommodation?",
        ],
        expect_escalated_on_turn={0: False},  # should be handled in-policy, not escalated
    )

    # Scenario 3 — Meher Kaur: 6h delay, full-night hotel ask + fare-diff switch request
    run_case(
        "Scenario 3: Meher Kaur — full-night hotel ask + fare-diff switch (>1500)",
        "WL7742",
        turns=[
            "My flight SK-305 is delayed 6 hours. I'd like a full night's hotel stay, not just the delayed hours. Also, can you just move me to a different flight instead of waiting? I'm told the fare difference is 2000 rupees.",
        ],
        expect_escalated_on_turn={0: True},  # fare-diff > 1500 must escalate
    )

    print(f"\n{'=' * 60}")
    print("Done. Review every reply above manually — the escalated-flag")
    print("checks are a safety net, not a substitute for reading the text.")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
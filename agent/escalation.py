"""
agent/escalation.py

Deterministic, rule-based checks — deliberately NOT left to the model's judgment.
These enforce the hard limits from policy_data.json (fare-difference cap, delay
bands, legal-action keywords) so compliance doesn't depend on the LLM remembering
a number correctly.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

AUDIT_LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "audit_trail.jsonl"

LEGAL_ESCALATION_PATTERNS = [
    r"\blegal action\b",
    r"\bformal complaint\b",
    r"\bsue\b",
    r"\blawyer\b",
    r"\bconsumer court\b",
]


def check_delay_compensation(delay_hours: float) -> list[str]:
    """Return the compensation entitlements for a given delay, per policy_data.json bands."""
    if delay_hours is None:
        return []
    if delay_hours > 5:
        return ["meal_voucher", "lounge_access", "hotel_delayed_hours_only"]
    if delay_hours > 3:
        return ["meal_voucher", "lounge_access"]
    if delay_hours < 3:
        return ["meal_voucher"]
    return ["meal_voucher", "lounge_access"]  # exactly 3h — treat as the >3h band


def check_fare_difference(amount_inr: float, waiver_limit: int = 1500) -> dict:
    """Decide whether an agent can approve a fare-difference waiver or must escalate."""
    if amount_inr is None:
        return {"can_approve": True, "escalate": False}
    if amount_inr > waiver_limit:
        return {"can_approve": False, "escalate": True,
                "reason": f"Fare difference ₹{amount_inr} exceeds agent waiver limit of ₹{waiver_limit}"}
    return {"can_approve": True, "escalate": False}


def detect_legal_escalation(customer_message: str) -> bool:
    """True if the customer's message mentions legal action / formal complaint — must escalate immediately."""
    text = customer_message.lower()
    return any(re.search(p, text) for p in LEGAL_ESCALATION_PATTERNS)


def detect_out_of_policy_request(customer_message: str) -> bool:
    """
    Lightweight keyword check for requests that are almost always out-of-policy
    (cash on top of a resolution, free upgrades 'for the trouble', full night hotel
    when only delayed-hours applies). This is a safety net, NOT the primary decision
    mechanism — the system prompt + model handle the actual reasoning; this just
    flags messages worth double-checking in the audit log.
    """
    text = customer_message.lower()
    flags = ["free upgrade", "full refund and", "full night", "compensation for the trouble",
             "waive the fare", "extra compensation"]
    return any(f in text for f in flags)


def log_action(customer: str, pnr: str, intent_detected: str, action_taken: str,
                escalated: bool, escalation_reason: str | None = None) -> None:
    """Append one structured record per turn — this IS the audit trail deliverable."""
    AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "customer": customer,
        "pnr": pnr,
        "intent_detected": intent_detected,
        "action_taken": action_taken,
        "escalated": escalated,
        "escalation_reason": escalation_reason,
    }
    with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
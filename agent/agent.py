"""
agent/agent.py

Decision logic (compensation bands, escalation triggers) is deterministic and
lives here + escalation.py, per the assignment's instruction to keep this
rule-based, not model-guessed.

Groq (free tier) is used for TWO things, both non-policy:
  1. Intent classification - "what is the customer asking about right now?"
     Groq returns ONLY a JSON label like {"intent": "flight_status"}. It never
     decides eligibility, amounts, or policy - that's 100% Python + escalation.py.
  2. Final phrasing - taking the facts Python already decided and phrasing them
     naturally.

If any Groq call fails for any reason (bad/missing key, rate limit, no
internet, bad JSON), we silently fall back to deterministic keyword matching
(for intent) or the plain template text (for phrasing), so the demo never
breaks.
"""

import json
import os
import re
from pathlib import Path

from escalation import (
    check_delay_compensation,
    check_fare_difference,
    detect_legal_escalation,
    log_action,
)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_PATH = BASE_DIR / "data" / "policy_data.json"

with open(DATA_PATH, "r", encoding="utf-8") as f:
    POLICY_DATA = json.load(f)

_conversations: dict = {}

SUPPORTED_INTENTS = {
    "flight_status",
    "disruption_options",
    "refund",
    "rebooking",
    "hotel",
    "meal_voucher",
    "lounge",
    "compensation",
    "upgrade",
    "general_question",
    "unknown",
}

# --- Optional Groq layer -------------------------------------------------
GROQ_MODEL = "llama-3.1-8b-instant"
_groq_client = None
if os.environ.get("GROQ_API_KEY"):
    try:
        from groq import Groq
        _groq_client = Groq(api_key=os.environ["GROQ_API_KEY"])
    except Exception:
        _groq_client = None  # groq package missing or bad key format - fall back silently


def _classify_intent_fallback(message: str) -> str:
    """Deterministic keyword-based intent classifier, used when Groq is
    unavailable or returns something unusable. Order matters - more specific
    checks come first."""
    text = message.lower()

    if any(k in text for k in ["upgrade", "business class", "first class"]):
        return "upgrade"
    if any(k in text for k in ["compensation", "make it up", "for the trouble", "extra money"]):
        return "compensation"
    if any(k in text for k in [
        "fare difference", "different flight", "another flight",
        "change my flight", "move me to", "switch flight", "rebook",
    ]):
        return "rebooking"
    if any(k in text for k in ["hotel", "accommodation", "full night", "entire night"]):
        return "hotel"
    if any(k in text for k in ["meal", "voucher", "food"]):
        return "meal_voucher"
    if "lounge" in text:
        return "lounge"
    if any(k in text for k in ["refund", "money back", "cash back"]):
        return "refund"
    if any(k in text for k in [
        "what time", "depart", "departure", "when does", "flight leave",
        "flight status", "new time",
    ]):
        return "flight_status"
    if any(k in text for k in [
        "what options", "what benefits", "what do i get", "what are my options",
        "entitled", "what happens now",
    ]):
        return "disruption_options"
    return "general_question"


def _classify_intent(message: str, history: list) -> str:
    """Ask Groq to label the customer's CURRENT intent, using recent history
    only as context (never as the thing being classified). Groq's output is
    validated against SUPPORTED_INTENTS and never used for anything except
    picking which Python branch to run - it cannot grant or deny anything."""
    if _groq_client is None:
        return _classify_intent_fallback(message)

    try:
        recent = history[-6:] if history else []
        history_text = "\n".join(f"{h['role']}: {h['message']}" for h in recent)

        response = _groq_client.chat.completions.create(
            model=GROQ_MODEL,
            max_tokens=30,
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You classify the CURRENT message of an airline customer support chat "
                        "into exactly one intent label. Respond with ONLY raw JSON, no markdown, "
                        "no explanation, in the form {\"intent\": \"<label>\"}.\n"
                        "Allowed labels: flight_status, disruption_options, refund, rebooking, "
                        "hotel, meal_voucher, lounge, compensation, upgrade, general_question, unknown.\n"
                        "Use recent conversation history only for context (e.g. resolving 'it' or "
                        "'that flight'). Classify the CURRENT message, not the whole conversation. "
                        "Do not decide whether the request is allowed - only label what it's about."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Recent history:\n{history_text}\n\nCurrent message: {message}",
                },
            ],
            timeout=8,
        )
        raw = response.choices[0].message.content.strip()
        raw = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
        parsed = json.loads(raw)
        intent = parsed.get("intent", "").strip().lower()
        if intent in SUPPORTED_INTENTS:
            return intent
        return _classify_intent_fallback(message)
    except Exception:
        return _classify_intent_fallback(message)


def _phrase_naturally(facts: str, customer_message: str) -> str | None:
    """Ask Groq to phrase the already-decided facts as a natural agent reply.
    Returns None on any failure so the caller can fall back to the template text."""
    if _groq_client is None:
        return None
    try:
        response = _groq_client.chat.completions.create(
            model=GROQ_MODEL,
            max_tokens=200,
            temperature=0.4,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an airline customer support agent. Rephrase the FACTS below "
                        "into a warm, natural, concise reply to the customer, focused on what "
                        "they just asked. Do not add, remove, or change any policy decision, "
                        "number, or amount. Do not invent anything not present in the facts. "
                        "Do not bring in unrelated facts the customer didn't ask about. "
                        "One short paragraph."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Customer said: {customer_message}\n\nFACTS (do not alter these decisions):\n{facts}",
                },
            ],
            timeout=8,
        )
        text = response.choices[0].message.content.strip()
        return text or None
    except Exception:
        return None
# ------------------------------------------------------------------------


def _find_customer(pnr):
    return next((c for c in POLICY_DATA["customers"] if c["pnr"] == pnr), None)


def _find_bookings(pnr):
    return [b for b in POLICY_DATA["bookings"] if b["pnr"] == pnr]


def _primary_disrupted_booking(bookings):
    for b in bookings:
        if b["status"] in ("cancelled", "delayed"):
            return b
    return bookings[0] if bookings else None


def _extract_fare_difference(message):
    match = re.search(r"₹\s?([\d,]+)", message)
    if match:
        return float(match.group(1).replace(",", ""))
    return None


def _handle_rebooking_ask(booking, customer_message, fare_diff):
    """Shared 'move me to a different flight' logic, usable regardless of
    whether the underlying booking is cancelled or delayed."""
    if fare_diff is None:
        fare_diff = _extract_fare_difference(customer_message)

    if fare_diff is None:
        return (
            "I can look into moving you to a different flight - could you tell me "
            "which one, so I can check the fare difference?",
            False, None,
        )

    decision = check_fare_difference(fare_diff)
    if decision["escalate"]:
        return (
            f"Moving to that flight involves a fare difference of Rs {fare_diff:.0f}, "
            f"which is above what I can approve myself - I'm escalating this to a supervisor.",
            True, decision["reason"],
        )
    return (
        f"I can move you to that flight for the Rs {fare_diff:.0f} fare difference - "
        f"let me know if you'd like to proceed.",
        False, None,
    )


def _handle_cancelled(booking, intent, customer_message, fare_diff):
    reply_parts, escalated, reasons = [], False, []
    cancel_info = (
        f"I can see {booking['flight']} ({booking['route']}) was cancelled due to "
        f"{booking.get('status_reason', 'operational reasons')}."
    )

    if intent == "refund":
        reply_parts.append(
            f"{cancel_info} Since this was an airline-caused cancellation, you're entitled "
            f"to a full refund to your original payment method, processed within 7 business days."
        )
    elif intent == "rebooking":
        text, esc, reason = _handle_rebooking_ask(booking, customer_message, fare_diff)
        reply_parts.append(f"{cancel_info} {text}")
        if esc:
            escalated, reasons = True, [reason]
    elif intent in ("hotel", "meal_voucher", "lounge"):
        reply_parts.append(
            f"{cancel_info} Since there's no delay involved here, hotel, meal voucher, and "
            f"lounge compensation don't apply - but you can choose a free rebooking on the "
            f"next available flight within 24 hours, or a full refund."
        )
    elif intent == "compensation":
        escalated, reasons = True, ["Requested compensation beyond standard policy"]
        reply_parts.append(
            f"{cancel_info} I'm not able to approve extra compensation beyond the standard "
            f"rebooking/refund options myself - I'm escalating this to a supervisor."
        )
    elif intent == "upgrade":
        escalated, reasons = True, ["Requested upgrade beyond standard policy"]
        reply_parts.append(
            f"{cancel_info} I'm not able to approve a complimentary upgrade myself - "
            f"I'm escalating that request to a supervisor."
        )
    else:  # flight_status, disruption_options, general_question, unknown
        reply_parts.append(
            f"{cancel_info} You're entitled to a free rebooking on the next available flight "
            f"within 24 hours, or a full refund - whichever you'd prefer."
        )

    return reply_parts, escalated, reasons


def _handle_delayed(booking, intent, customer_message, fare_diff):
    reply_parts, escalated, reasons = [], False, []
    delay_hours = booking["delay_hours"]
    new_dep = booking.get("new_departure")
    comp = check_delay_compensation(delay_hours)

    if intent == "flight_status":
        reply_parts.append(
            f"Your flight {booking['flight']} is now scheduled to depart at {new_dep} "
            f"(delayed {delay_hours} hours)."
        )
    elif intent == "hotel":
        if "hotel_delayed_hours_only" in comp:
            reply_parts.append(
                f"Since your flight is delayed {delay_hours} hours, hotel accommodation is "
                f"available, but only for the delayed-hours portion, not a full night's stay."
            )
        else:
            reply_parts.append(
                f"Hotel accommodation only applies to delays over 5 hours, and your flight "
                f"is delayed {delay_hours} hours, so that's not available here."
            )
    elif intent == "meal_voucher":
        if "meal_voucher" in comp:
            reply_parts.append("A meal voucher is available for your booking given the delay.")
        else:
            reply_parts.append("A meal voucher isn't applicable for this delay.")
    elif intent == "lounge":
        if "lounge_access" in comp:
            reply_parts.append("Lounge access is available for your booking given the delay.")
        else:
            reply_parts.append(
                f"Lounge access applies to delays over 3 hours; your flight is delayed "
                f"{delay_hours} hours, so that's not available here."
            )
    elif intent == "disruption_options":
        comp_text = ", ".join(c.replace("_", " ") for c in comp)
        reply_parts.append(
            f"Your flight {booking['flight']} is delayed {delay_hours} hours "
            f"(new departure {new_dep}). That qualifies you for: {comp_text}. "
            f"These benefits are available for your booking."
        )
    elif intent == "refund":
        reply_parts.append(
            "Since this flight is delayed rather than cancelled, a refund isn't applicable - "
            "but the delay compensation for your flight's delay length is available if you'd "
            "like the details."
        )
    elif intent == "rebooking":
        text, esc, reason = _handle_rebooking_ask(booking, customer_message, fare_diff)
        reply_parts.append(text)
        if esc:
            escalated, reasons = True, [reason]
    elif intent == "compensation":
        escalated, reasons = True, ["Requested compensation beyond standard policy"]
        reply_parts.append(
            "I'm not able to approve extra compensation beyond the standard delay policy "
            "myself - I'm escalating this to a supervisor."
        )
    elif intent == "upgrade":
        escalated, reasons = True, ["Requested upgrade beyond standard policy"]
        reply_parts.append(
            "I'm not able to approve a complimentary upgrade myself - I'm escalating that "
            "request to a supervisor."
        )
    else:  # general_question, unknown
        comp_text = ", ".join(c.replace("_", " ") for c in comp)
        reply_parts.append(
            f"Your flight {booking['flight']} is delayed {delay_hours} hours "
            f"(new departure {new_dep}). That qualifies you for: {comp_text}. "
            f"These benefits are available for your booking."
        )

    return reply_parts, escalated, reasons


def handle_message(pnr, customer_message, fare_diff=None):
    """
    fare_diff: pass this in when your front-end / flight-search step already
    knows the fare difference for the flight the customer wants to switch to
    (this is the normal case - customers don't quote fare figures themselves).
    If omitted, we fall back to scanning the message text for a ₹ amount,
    which only helps if the number happens to be typed out.
    """
    customer = _find_customer(pnr)
    if customer is None:
        return {"reply": "I couldn't find a booking under that reference - could you double-check the PNR?",
                "escalated": False}

    bookings = _find_bookings(pnr)
    booking = _primary_disrupted_booking(bookings)

    history = _conversations.setdefault(pnr, [])
    history.append({"role": "customer", "message": customer_message})

    if detect_legal_escalation(customer_message):
        reply = ("I hear you, and I'm sorry this has been frustrating. I'm escalating this "
                 "to our specialist support team right now - they'll reach out to you directly.")
        history.append({"role": "agent", "message": reply})
        log_action(customer["name"], pnr, "legal_escalation", "escalated_to_human",
                   escalated=True, escalation_reason="Customer mentioned legal action / formal complaint")
        return {"reply": reply, "escalated": True}

    # --- Groq: classify intent only. Python still owns every policy decision. ---
    intent = _classify_intent(customer_message, history[:-1])

    if booking is None:
        reply_parts = ["I don't see any disrupted flight on this booking - could you tell me more?"]
        escalated, escalation_reasons = False, []
    elif booking["status"] == "cancelled":
        reply_parts, escalated, escalation_reasons = _handle_cancelled(
            booking, intent, customer_message, fare_diff
        )
    elif booking["status"] == "delayed":
        reply_parts, escalated, escalation_reasons = _handle_delayed(
            booking, intent, customer_message, fare_diff
        )
    else:
        reply_parts = ["Could you tell me a bit more about what you need help with on this booking?"]
        escalated, escalation_reasons = False, []

    if not reply_parts:
        reply_parts = ["Could you tell me a bit more about what you need help with on this booking?"]

    reply = " ".join(reply_parts)

    natural_reply = _phrase_naturally(reply, customer_message)
    final_reply = natural_reply if natural_reply else reply

    history.append({"role": "agent", "message": final_reply})

    log_action(
        customer["name"], pnr,
        intent_detected=intent,
        action_taken=final_reply[:120] + ("..." if len(final_reply) > 120 else ""),
        escalated=escalated,
        escalation_reason="; ".join(escalation_reasons) if escalation_reasons else None,
    )

    return {"reply": final_reply, "escalated": escalated}


if __name__ == "__main__":
    print("--- Scenario 1: Priya (cancelled + upgrade ask) ---")
    print(handle_message("SK4821X", "Hi, my flight SK-204 to Goa got cancelled, what are my options?")["reply"])
    print()
    print(handle_message("SK4821X", "I'm furious. I want a full cash refund plus a free business class upgrade for the trouble.")["reply"])
    print()

    print("--- Scenario 2: Arvind (4h delay - multi-turn, different intents) ---")
    print(handle_message("TR1190B", "My flight is delayed 4 hours.")["reply"])
    print()
    print(handle_message("TR1190B", "What time does my flight leave now?")["reply"])
    print()
    print(handle_message("TR1190B", "Can I get a hotel?")["reply"])
    print()
    print(handle_message("TR1190B", "What benefits do I get?")["reply"])
    print()
    print(handle_message("TR1190B", "Can you move me to a different flight? Fare difference is ₹2000.")["reply"])
    print()

    print("--- Scenario 3: Meher (6h delay, full night hotel + different flight, fare_diff passed in) ---")
    print(handle_message("WL7742", "I want a full-night hotel.")["reply"])
    print()
    print(handle_message(
        "WL7742",
        "I want another flight instead of waiting.",
        fare_diff=2000,
    )["reply"])
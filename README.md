# Airline Disruption Resolution Agent

A customer-facing chat agent that handles flight cancellations and delays — grounded entirely in a fixed policy dataset, with every compensation/refund/escalation decision made by deterministic rules, not by the LLM's judgment.

Built for Assignment 3 (AIONOS): *Customer-Facing Resolution Agent — Airline Disruption*.

---

## What this does

A customer messages the agent about their disrupted flight. The agent:

- Looks up their booking and status from `data/policy_data.json`
- Figures out what they're asking about (refund, hotel, rebooking, etc.)
- Applies the exact policy rules (delay-compensation bands, fare-difference cap, cancellation rules) to decide the correct action
- Replies in natural language
- **Escalates to a human** the moment a request goes beyond what it's allowed to approve
- Logs every turn — intent, action, and escalation status — to an audit trail

Only the three sample customers from the data pack (Priya, Arvind, Meher) are seeded in the dataset.

---

## Why it's built this way

The LLM is only used for two things:
1. **Intent classification** — labeling what the customer's current message is about
2. **Reply phrasing** — turning an already-decided fact into a natural sentence

Every actual policy decision — delay bands, the ₹1,500 fare-difference waiver limit, cancellation entitlements, escalation triggers — lives in plain Python (`agent/escalation.py`, `agent/agent.py`). This keeps compliance deterministic: the same input always produces the same compliant output, and nothing is left to the model to remember or improvise.

If the LLM call fails or no API key is set, the agent silently falls back to keyword-based intent matching and template replies — the demo never breaks.

---

## Project structure

```
airline-resolution-agent/
├── README.md                # this file
├── .env.example              # placeholder for GROQ_API_KEY
├── .gitignore
│
├── data/
│   └── policy_data.json      # customers, bookings, service rules, allowed/prohibited actions
│
├── agent/
│   ├── system_prompt.md      # grounding rules, decision order, escalation triggers, tone
│   ├── agent.py               # orchestration: intent classification, policy dispatch, LLM phrasing
│   └── escalation.py          # deterministic checks: delay bands, fare-diff cap, legal-language detection, audit logging
│
├── logs/
│   └── audit_trail.jsonl     # one JSON record per conversation turn (appended, never overwritten)
│
├── server/
│   ├── app.py                 # backend API — receives chat messages, calls agent/
│   └── routes.py              # /chat, /history endpoints
│
├── frontend/
│   ├── index.html
│   ├── chat.js                 # talks to server/app.py, renders chat + escalation banner
│   └── style.css
│
├── tests/
│   └── test_scenarios.py      # runs the 3 required scenarios, checks expected agent behavior

---

## Setup

### Requirements
- Python 3.10+
- A free [Groq](https://console.groq.com) API key *(optional — the agent works without one, using rule-based fallbacks)*

### 1. Clone and install
```bash
git clone <repo-url>
cd airline-resolution-agent
pip install -r requirements.txt
```

### 2. Configure your API key
```bash
cp .env.example .env
```
Then open `.env` and add:
```
GROQ_API_KEY=your_key_here
```
Leave it blank to run entirely on the deterministic fallback (no LLM calls at all).

### 3. Run the backend
```bash
python server/app.py
```
This starts the API on `http://localhost:5000`.

### 4. Open the frontend
Open `frontend/index.html` in your browser (or serve the `frontend/` folder with any static server). Pick a customer PNR from the dropdown and start chatting.

> If you deploy the backend somewhere other than `localhost:5000`, update `API_BASE` in `frontend/chat.js`.

---

## Try it — sample flow

Pick **SK4821X — Priya Nair** and send:

```
Hi, my flight to Goa got cancelled, what are my options?
```
→ Agent offers free rebooking within 24h or a full refund.

Then send:
```
I'm furious. I want a full cash refund plus a free business class upgrade for the trouble.
```
→ Escalation banner triggers — a free upgrade is compensation beyond policy.

Two other seeded customers to try: **TR1190B — Arvind Kulkarni** (4h delay) and **WL7742 — Meher Kaur** (6h delay, asks for a full-night hotel and a ₹2,000 fare-difference switch).

---

## Running the test scenarios

```bash
python tests/test_scenarios.py
```
Runs all three required scenarios from the data pack against the agent and checks the expected in-policy actions and escalation triggers.

---

## Audit trail

Every conversation turn is appended to `logs/audit_trail.jsonl` as a structured record:

```json
{
  "timestamp": "...",
  "customer": "Priya Nair",
  "pnr": "SK4821X",
  "intent_detected": "upgrade",
  "action_taken": "...",
  "escalated": true,
  "escalation_reason": "Requested upgrade beyond standard policy"
}
```

This is a mandatory deliverable, not optional logging — it's how every decision the agent makes can be reviewed after the fact.

---

## Key design decisions

- **Policy logic is code, not prompt.** Delay-compensation bands, the ₹1,500 fare-waiver cap, and escalation triggers are hardcoded checks in `escalation.py`, so they can't drift or be "argued around" by a cleverly worded customer message.
- **Grounding is enforced, not just requested.** The agent only uses facts present in `policy_data.json` and is instructed to say so and escalate rather than guess when something isn't covered.
- **Legal language always escalates immediately** — even mid-conversation, even if the rest of the request is otherwise resolvable.
- **Loyalty tier affects rebooking priority only** — never extra compensation, regardless of how the customer frames the request.
- **Graceful degradation** — if the Groq API is unreachable, rate-limited, or no key is set, the agent falls back to keyword-based intent matching and template replies rather than failing.

---

## Known limitations

- Audit log is a local JSONL file — fine for a prototype, would move to a proper database in production.
- Fare difference is expected to come from a flight-search step in a real system; scanning the customer's message text for a ₹ amount is a fallback used only for this demo.
- Only the three customers/bookings in the data pack are supported — there's no general account lookup.

---

## Links

- GitHub: *[https://github.com/Monikanahadiya]*

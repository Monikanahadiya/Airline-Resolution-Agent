// frontend/chat.js
// Talks to server/app.py. Change API_BASE if you deploy the backend elsewhere.

const API_BASE = "http://localhost:5000";

const pnrInput = document.getElementById("pnr-input");
const chatWindow = document.getElementById("chat-window");
const chatForm = document.getElementById("chat-form");
const messageInput = document.getElementById("message-input");
const escalationBanner = document.getElementById("escalation-banner");

function addMessage(text, sender) {
  const bubble = document.createElement("div");
  bubble.className = `bubble ${sender}`;
  bubble.textContent = text;
  chatWindow.appendChild(bubble);
  chatWindow.scrollTop = chatWindow.scrollHeight;
}

function setEscalated(isEscalated) {
  escalationBanner.classList.toggle("hidden", !isEscalated);
}

// Reset the visible thread when switching customers (doesn't clear server-side
// history — that's intentional, so a reviewer can switch back and still see
// the audit trail persisted for /history/<pnr>)
pnrInput.addEventListener("change", () => {
  chatWindow.innerHTML = "";
  setEscalated(false);
});

chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const message = messageInput.value.trim();
  const pnr = pnrInput.value;
  if (!message) return;

  addMessage(message, "customer");
  messageInput.value = "";
  messageInput.disabled = true;

  const thinkingBubble = document.createElement("div");
  thinkingBubble.className = "bubble agent thinking";
  thinkingBubble.textContent = "...";
  chatWindow.appendChild(thinkingBubble);
  chatWindow.scrollTop = chatWindow.scrollHeight;

  try {
    const res = await fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pnr, message }),
    });

    const data = await res.json();
    thinkingBubble.remove();

    if (!res.ok) {
      addMessage(data.error || "Something went wrong.", "agent error");
      return;
    }

    addMessage(data.reply, "agent");
    setEscalated(Boolean(data.escalated));
  } catch (err) {
    thinkingBubble.remove();
    addMessage("Couldn't reach the server — is server/app.py running on port 5000?", "agent error");
  } finally {
    messageInput.disabled = false;
    messageInput.focus();
  }
});
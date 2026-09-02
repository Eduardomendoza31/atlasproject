const chatEl = document.getElementById("chat");
const form = document.getElementById("composer");
const input = document.getElementById("input");

let ws = null;
let atlasBubble = null;

function addMessage(text, who) {
  const div = document.createElement("div");
  div.className = `msg ${who}`;
  div.textContent = text;
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
  return div;
}

function connect() {
  ws = new WebSocket("ws://127.0.0.1:8731/ws/chat");

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === "chunk") {
      if (typingBubble) {
        typingBubble.remove();
        typingBubble = null;
      }
      if (!atlasBubble) {
        atlasBubble = addMessage("", "atlas");
      }
      atlasBubble.textContent += data.text;
      chatEl.scrollTop = chatEl.scrollHeight;
    } else if (data.type === "done") {
      atlasBubble = null;
    } else if (data.type === "error") {
      if (typingBubble) {
        typingBubble.remove();
        typingBubble = null;
      }
      atlasBubble = null;
      addMessage(`⚠️ ${data.text}`, "atlas");
    }
  };

  ws.onclose = () => {
    setTimeout(connect, 1000);
  };
}

connect();

let typingBubble = null;

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    addMessage("⚠️ Sin conexión con Atlas, reintentando...", "atlas");
    return;
  }
  addMessage(text, "user");
  ws.send(text);
  input.value = "";
  typingBubble = addMessage("escribiendo…", "atlas typing");
});

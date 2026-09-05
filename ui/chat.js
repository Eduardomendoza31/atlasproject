// Capa de chat: websocket, mensajes, confirmaciones de herramientas,
// envio de texto/audio. No conoce como se ve la interfaz nueva - avisa
// lo que pasa mediante CustomEvent en window ("atlas:state", "atlas:tool")
// para que app.js pueda dibujar estados/actividad sin acoplarse aca.
//
// No toca nada de face.js: cuando necesita saber si se esta grabando
// audio, observa la clase "recording" del propio boton del mic (que
// face.js sigue prendiendo/apagando el solo) en vez de intervenir en esa
// logica.

const chatEl = document.getElementById("chat");
const form = document.getElementById("composer");
const input = document.getElementById("input");
const stopButton = document.getElementById("stop-button");

let ws = null;
let atlasBubble = null;
let typingBubble = null;

// Mismos niveles de riesgo que core/tools.py (duplicado a proposito -
// son 5 strings constantes, no vale la pena un endpoint solo para esto).
const TOOL_TIERS = {
  read_file: "safe",
  list_directory: "safe",
  write_file: "sensitive",
  run_command: "critical",
  web_search: "safe",
};
const TIER_EMOJI = { safe: "🟢", sensitive: "🟡", critical: "🔴" };

let turnInFlight = false;
let pendingConfirmId = null;

function setAtlasState(state) {
  window.dispatchEvent(new CustomEvent("atlas:state", { detail: { state } }));
}

function emitTool(detail) {
  window.dispatchEvent(new CustomEvent("atlas:tool", { detail }));
}

function setTurnInFlight(inFlight) {
  turnInFlight = inFlight;
  stopButton.disabled = !inFlight;
}

function setComposerEnabled(enabled) {
  input.disabled = !enabled;
  form.querySelector('button[type="submit"]').disabled = !enabled;
  document.getElementById("mic-button").disabled = !enabled;
}

function addMessage(text, who) {
  const div = document.createElement("div");
  div.className = `msg ${who}`;
  div.textContent = text;
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;
  return div;
}

function clearTyping() {
  if (typingBubble) {
    typingBubble.remove();
    typingBubble = null;
  }
}

function addConfirmBubble({ id, name, tier, description }) {
  setComposerEnabled(false);
  pendingConfirmId = id;
  const div = document.createElement("div");
  div.className = `msg atlas confirm confirm-${tier}`;
  const tierLabel = tier === "critical" ? "🔴 Acción crítica" : "🟡 Confirmación requerida";

  const label = document.createElement("div");
  label.className = "confirm-label";
  label.textContent = tierLabel;

  const desc = document.createElement("div");
  desc.className = "confirm-desc";
  desc.textContent = description;

  const actions = document.createElement("div");
  actions.className = "confirm-actions";
  const approveBtn = document.createElement("button");
  approveBtn.type = "button";
  approveBtn.className = "confirm-approve";
  approveBtn.textContent = "Permitir";
  const denyBtn = document.createElement("button");
  denyBtn.type = "button";
  denyBtn.className = "confirm-deny";
  denyBtn.textContent = "Denegar";
  actions.appendChild(approveBtn);
  actions.appendChild(denyBtn);

  div.appendChild(label);
  div.appendChild(desc);
  div.appendChild(actions);
  chatEl.appendChild(div);
  chatEl.scrollTop = chatEl.scrollHeight;

  approveBtn.addEventListener("click", () => resolveConfirm(id, true, div));
  denyBtn.addEventListener("click", () => resolveConfirm(id, false, div));
}

function resolveConfirm(id, approved, bubbleEl) {
  sendMessage({ type: "tool_confirm_response", id, approved });
  bubbleEl.querySelector(".confirm-actions").remove();
  bubbleEl.classList.add(approved ? "confirm-resolved-yes" : "confirm-resolved-no");
  if (pendingConfirmId === id) {
    pendingConfirmId = null;
    setComposerEnabled(true);
  }
}

function connect() {
  ws = new WebSocket("ws://127.0.0.1:8731/ws/chat");

  ws.onopen = () => setAtlasState("listo");

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === "transcript") {
      addMessage(data.text, "user");
      typingBubble = addMessage("escribiendo…", "atlas typing");
      setTurnInFlight(true);
      setAtlasState("procesando");
    } else if (data.type === "chunk") {
      clearTyping();
      if (!atlasBubble) {
        atlasBubble = addMessage("", "atlas");
      }
      atlasBubble.textContent += data.text;
      chatEl.scrollTop = chatEl.scrollHeight;
      setAtlasState("procesando");
    } else if (data.type === "done") {
      atlasBubble = null;
      setTurnInFlight(false);
      setAtlasState("listo");
    } else if (data.type === "error") {
      clearTyping();
      atlasBubble = null;
      setTurnInFlight(false);
      setAtlasState("listo");
      addMessage(`⚠️ ${data.text}`, "atlas");
    } else if (data.type === "audio_reply") {
      const audio = new Audio(`data:audio/mpeg;base64,${data.data}`);
      audio.addEventListener("play", () => setAtlasState("hablando"));
      audio.addEventListener("ended", () => setAtlasState("listo"));
      playWithLipSync(audio);
    } else if (data.type === "tool_call") {
      clearTyping();
      const tier = TOOL_TIERS[data.name] || "safe";
      if (data.name === "announce_plan") {
        const steps = data.arguments.steps || [];
        const list = steps.map((s, i) => `${i + 1}. ${s}`).join("\n");
        addMessage(`📋 Plan:\n${list}`, "atlas plan-announce");
      } else if (data.name === "report_outcome") {
        const { summary, verified, success } = data.arguments;
        const badge = success ? (verified ? "✅ Hecho y verificado" : "⚠️ Hecho, sin verificar") : "❌ No se logró";
        addMessage(`${badge}: ${summary}`, "atlas outcome-report");
      } else {
        addMessage(
          `${TIER_EMOJI[tier]} Atlas usa: ${data.name}(${JSON.stringify(data.arguments)})`,
          "atlas tool-call"
        );
      }
      emitTool({ phase: "call", id: data.id, name: data.name, arguments: data.arguments, tier });
      setAtlasState("ejecutando");
    } else if (data.type === "tool_confirm_request") {
      clearTyping();
      addConfirmBubble(data);
      emitTool({
        phase: "confirm",
        id: data.id,
        name: data.name,
        tier: data.tier,
        description: data.description,
      });
      setAtlasState("autorizacion");
    } else if (data.type === "tool_result") {
      // announce_plan/report_outcome ya mostraron su propio mensaje al
      // llegar como tool_call (con los datos reales del plan/resultado) -
      // el "resultado" de estas dos es solo un acuse interno, no aporta
      // nada nuevo en pantalla.
      if (data.name !== "announce_plan" && data.name !== "report_outcome") {
        const label = data.denied ? "denegado" : "resultado";
        addMessage(`${data.name} — ${label}: ${data.result}`, "atlas tool-result");
      }
      emitTool({
        phase: "result",
        id: data.id,
        name: data.name,
        result: data.result,
        denied: data.denied,
      });
      setAtlasState("ejecutando");
    } else if (data.type === "stopped") {
      clearTyping();
      atlasBubble = null;
      setTurnInFlight(false);
      if (pendingConfirmId) {
        pendingConfirmId = null;
        setComposerEnabled(true);
      }
      addMessage("⏹ Turno detenido.", "atlas");
      setAtlasState("listo");
    }
  };

  ws.onclose = () => {
    setAtlasState("desconectado");
    setTimeout(connect, 1000);
  };
}

connect();

function sendMessage(payload) {
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    addMessage("⚠️ Sin conexión con Atlas, reintentando...", "atlas");
    return false;
  }
  ws.send(JSON.stringify(payload));
  return true;
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  if (!sendMessage({ type: "text", text })) return;
  addMessage(text, "user");
  input.value = "";
  typingBubble = addMessage("escribiendo…", "atlas typing");
  setTurnInFlight(true);
  setAtlasState("procesando");
});

stopButton.addEventListener("click", () => {
  sendMessage({ type: "stop" });
});

// El estado "escuchando" se deriva observando la clase "recording" que
// face.js ya prende/apaga por su cuenta en el boton del mic - no se
// toca esa logica, solo se mira desde afuera.
const micButtonForState = document.getElementById("mic-button");
new MutationObserver(() => {
  if (turnInFlight) return; // no pisar un estado de turno real en curso
  setAtlasState(micButtonForState.classList.contains("recording") ? "escuchando" : "listo");
}).observe(micButtonForState, { attributes: true, attributeFilter: ["class"] });

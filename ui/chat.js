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

// Si el turno actual empezo por voz (llego un "transcript"), cuando
// termine de hablar la respuesta se vuelve a activar el microfono solo -
// asi una conversacion hablada puede seguir de corrido sin tocar nada.
// Si el usuario escribio en vez de hablar, no se activa el microfono
// solo (no tiene sentido prender el mic porque escribio algo).
let lastTurnWasVoice = false;

function maybeResumeListening() {
  if (!lastTurnWasVoice || turnInFlight) return;
  // Solo se reactiva UNA vez sola por respuesta hablada, no en cadena
  // indefinida - si se dejara lastTurnWasVoice en true aca, cualquier
  // palabra suelta que el microfono agarre (ruido de fondo, etc.)
  // generaria otra respuesta hablada, que reactivaria el mic de nuevo,
  // sin ninguna forma real de que se detenga sola.
  lastTurnWasVoice = false;
  const micButton = document.getElementById("mic-button");
  if (micButton && !micButton.disabled && !micButton.classList.contains("recording")) {
    micButton.click();
  }
}

// Nivel de riesgo de cada herramienta, para el emoji del primer aviso
// ("Atlas usa: tool(args)") antes de que llegue (si aplica) la burbuja
// de confirmacion real. Arranca con los 4 basicos como resguardo (por si
// el fetch todavia no responde cuando llega el primer tool_call) y se
// completa con la lista real del backend - las skills agregan tools
// nuevas todo el tiempo (documentos, automatizaciones, vision, etc.) y
// una lista fija hardcodeada quedaria desactualizada de nuevo.
const TOOL_TIERS = {
  read_file: "safe",
  list_directory: "safe",
  write_file: "sensitive",
  run_command: "critical",
};
const TIER_EMOJI = { safe: "🟢", sensitive: "🟡", critical: "🔴" };

fetch("http://127.0.0.1:8731/tools")
  .then((r) => r.json())
  .then((data) => {
    (data.tools || []).forEach((t) => { TOOL_TIERS[t.name] = t.tier; });
  })
  .catch(() => {});

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

  // Herramientas como run_command mandan "explicacion simple\n\n🔧 comando
  // tecnico" (ver core/tools.py) - se separa en dos partes con estilos
  // distintos para que lo primero que se lea sea la explicacion en
  // español simple, no la sintaxis. Si no hay marcador (la mayoria de
  // las herramientas), se muestra tal cual, como antes.
  const desc = document.createElement("div");
  desc.className = "confirm-desc";
  const marker = "\n\n🔧 ";
  const markerIndex = description.indexOf(marker);
  if (markerIndex === -1) {
    desc.textContent = description;
  } else {
    desc.appendChild(document.createTextNode(description.slice(0, markerIndex)));
    const tech = document.createElement("span");
    tech.className = "confirm-technical";
    tech.textContent = description.slice(markerIndex + marker.length);
    desc.appendChild(tech);
  }

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
      lastTurnWasVoice = true;
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
      audio.addEventListener("ended", () => {
        setAtlasState("listo");
        // Pequeña pausa antes de reactivar el mic - si se hace en el
        // instante mismo en que termina el audio, a veces el propio
        // altavoz/eco del final de la frase se cuela en la grabacion.
        setTimeout(maybeResumeListening, 400);
      });
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
    } else if (data.type === "subagent_call") {
      clearTyping();
      addMessage(`🤖 Atlas delega en ${data.agent_name}: ${data.task}`, "atlas subagent-call");
      window.dispatchEvent(new CustomEvent("atlas:subagent", { detail: { phase: "start", agent: data.agent_name } }));
      setAtlasState("ejecutando");
    } else if (data.type === "subagent_result") {
      addMessage(`${data.agent_name} completó su tarea: ${data.result}`, "atlas subagent-result");
      window.dispatchEvent(new CustomEvent("atlas:subagent", { detail: { phase: "done", agent: data.agent_name } }));
      setAtlasState("ejecutando");
    } else if (data.type === "stopped") {
      lastTurnWasVoice = false;
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
  if (!text && !pendingAttachment) return;
  lastTurnWasVoice = false;
  const payload = { type: "text", text };
  if (pendingAttachment) payload.attachment = pendingAttachment;
  if (!sendMessage(payload)) return;
  addMessage(text + (pendingAttachment ? `\n📎 ${pendingAttachment.filename}` : ""), "user");
  input.value = "";
  clearAttachment();
  typingBubble = addMessage("escribiendo…", "atlas typing");
  setTurnInFlight(true);
  setAtlasState("procesando");
});

// --- Adjuntar imagen o PDF: se lee como base64 en el navegador y se
// manda junto con el proximo mensaje (o solo, con un texto por defecto
// si el usuario no escribe nada) - Atlas lo interpreta como una imagen
// mas en la conversacion, igual que la captura de pantalla de
// skills/vision.py, asi que no hizo falta ningun cambio en el modelo.
const ATTACHMENT_MAX_BYTES = 15 * 1024 * 1024;
const attachButton = document.getElementById("attach-button");
const fileInput = document.getElementById("file-input");
const attachmentChip = document.getElementById("attachment-chip");
const attachmentNameEl = document.getElementById("attachment-name");
const attachmentRemoveBtn = document.getElementById("attachment-remove");
let pendingAttachment = null;

function clearAttachment() {
  pendingAttachment = null;
  attachmentChip.hidden = true;
  attachmentNameEl.textContent = "";
  fileInput.value = "";
}

attachButton.addEventListener("click", () => fileInput.click());

fileInput.addEventListener("change", () => {
  const file = fileInput.files[0];
  if (!file) return;
  if (file.size > ATTACHMENT_MAX_BYTES) {
    addMessage(`⚠️ "${file.name}" pesa demasiado (máximo 15 MB).`, "atlas");
    fileInput.value = "";
    return;
  }
  const reader = new FileReader();
  reader.onload = () => {
    // reader.result es "data:<mime>;base64,<datos>" - solo se necesita
    // la parte de despues de la coma.
    const base64 = reader.result.split(",", 2)[1] || "";
    pendingAttachment = { filename: file.name, mime_type: file.type || "application/octet-stream", data: base64 };
    attachmentNameEl.textContent = file.name;
    attachmentChip.hidden = false;
    input.focus();
  };
  reader.onerror = () => addMessage(`⚠️ No pude leer "${file.name}".`, "atlas");
  reader.readAsDataURL(file);
});

attachmentRemoveBtn.addEventListener("click", clearAttachment);

stopButton.addEventListener("click", () => {
  // "Detener" ahora tambien sirve como el boton para cortar el modo voz:
  // si el microfono esta escuchando, lo apaga (dispara stopRecording en
  // face.js) y se asegura de que no se vuelva a prender solo despues.
  if (micButtonForState.classList.contains("recording")) {
    lastTurnWasVoice = false;
    micButtonForState.click();
  }
  sendMessage({ type: "stop" });
});

// El estado "escuchando" se deriva observando la clase "recording" que
// face.js ya prende/apaga por su cuenta en el boton del mic - no se
// toca esa logica, solo se mira desde afuera.
const micButtonForState = document.getElementById("mic-button");
new MutationObserver(() => {
  const recording = micButtonForState.classList.contains("recording");
  // "Detener" antes solo se habilitaba con un turno en curso en el
  // servidor - mientras el mic estaba escuchando (todavia nada enviado)
  // se quedaba deshabilitado, sin ninguna forma visible de cortar la
  // escucha. Ahora tambien se habilita mientras esta grabando.
  stopButton.disabled = !(turnInFlight || recording);
  if (turnInFlight) return; // no pisar un estado de turno real en curso
  setAtlasState(recording ? "escuchando" : "listo");
}).observe(micButtonForState, { attributes: true, attributeFilter: ["class"] });

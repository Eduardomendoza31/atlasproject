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

// --- Modo voz continuo ---
// Al tocar el mic por primera vez se arma "voiceLoopActive": mientras
// siga armado, cuando termine de hablar la respuesta el mic se vuelve a
// prender solo (conversacion hablada de corrido, sin tocar nada entre
// frases), y ademas un detector de silencio (VAD, mas abajo) corta la
// grabacion solo cuando detecta que el usuario dejo de hablar, sin que
// haga falta tocar el mic para "enviar". Se apaga con la X que aparece
// pegada al mic mientras esta armado, con "Detener", o escribiendo en
// vez de hablar - todas formas explicitas, nunca solo.
let voiceLoopActive = false;
const micButtonForState = document.getElementById("mic-button");
const micWrap = document.querySelector(".mic-wrap");
const voiceLoopExit = document.getElementById("voice-loop-exit");

function setVoiceLoopActive(active) {
  voiceLoopActive = active;
  micWrap.classList.toggle("loop-active", active);
  voiceLoopExit.hidden = !active;
}

function maybeResumeListening() {
  if (!voiceLoopActive || turnInFlight) return;
  if (!micButtonForState.disabled && !micButtonForState.classList.contains("recording")) {
    micButtonForState.click();
  }
}

voiceLoopExit.addEventListener("click", () => {
  setVoiceLoopActive(false);
  if (micButtonForState.classList.contains("recording")) {
    micButtonForState.click();
  }
});

// --- Deteccion de fin de frase (VAD) ---
// face.js (protegido, no se toca) solo sabe prender/apagar la grabacion
// con un click - no avisa cuando el usuario deja de hablar. En vez de
// tocar esa logica, se abre un SEGUNDO stream de microfono, aparte,
// nada mas para medir el volumen (RMS) y decidir cuando hubo silencio
// despues de haber habido voz - al detectarlo, se hace click en el
// mismo boton del mic, que es lo que de verdad corta+envia la
// grabacion real (esa la sigue manejando face.js, intacta).
const VAD_SPEECH_RMS = 0.02;
const VAD_SILENCE_MS = 1300;
let vadStream = null;
let vadContext = null;
let vadRAF = null;

function stopVAD() {
  if (vadRAF) cancelAnimationFrame(vadRAF);
  vadRAF = null;
  if (vadStream) {
    vadStream.getTracks().forEach((t) => t.stop());
    vadStream = null;
  }
  if (vadContext) {
    vadContext.close().catch(() => {});
    vadContext = null;
  }
}

async function startVAD() {
  stopVAD();
  try {
    vadStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch {
    return; // sin VAD el usuario sigue pudiendo cortar a mano con el mic
  }
  vadContext = new AudioContext();
  const source = vadContext.createMediaStreamSource(vadStream);
  const analyser = vadContext.createAnalyser();
  analyser.fftSize = 512;
  source.connect(analyser);
  const data = new Uint8Array(analyser.fftSize);
  let hasSpeech = false;
  let silenceStartedAt = null;

  const tick = () => {
    if (!micButtonForState.classList.contains("recording")) {
      stopVAD();
      return;
    }
    analyser.getByteTimeDomainData(data);
    let sumSquares = 0;
    for (let i = 0; i < data.length; i++) {
      const v = (data[i] - 128) / 128;
      sumSquares += v * v;
    }
    const rms = Math.sqrt(sumSquares / data.length);
    if (rms > VAD_SPEECH_RMS) {
      hasSpeech = true;
      silenceStartedAt = null;
    } else if (hasSpeech) {
      if (silenceStartedAt === null) {
        silenceStartedAt = performance.now();
      } else if (performance.now() - silenceStartedAt > VAD_SILENCE_MS) {
        stopVAD();
        micButtonForState.click();
        return;
      }
    }
    vadRAF = requestAnimationFrame(tick);
  };
  vadRAF = requestAnimationFrame(tick);
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
let pendingConfirmBubbleEl = null;

// Palabras sueltas para interpretar un "si"/"no" hablado como respuesta
// a una confirmacion, sin necesitar una frase exacta. Deliberadamente
// simple (coincidencia de palabras, no NLP) - si no reconoce ninguna,
// se le pide al usuario que lo aclare en vez de adivinar.
const CONFIRM_YES_WORDS = ["si", "sí", "claro", "dale", "permite", "permitir", "acepto", "adelante", "hazlo", "confirmo", "ok", "okay", "vale", "correcto"];
const CONFIRM_NO_WORDS = ["no", "cancela", "cancelar", "deniega", "denegar", "para", "detente", "negativo"];

function matchYesNo(text) {
  const normalized = text.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^\w\s]/g, "");
  const words = normalized.split(/\s+/);
  if (words.some((w) => CONFIRM_NO_WORDS.includes(w))) return false;
  if (words.some((w) => CONFIRM_YES_WORDS.includes(w))) return true;
  return null;
}

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
  const wasVoiceLoop = voiceLoopActive;
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

  pendingConfirmBubbleEl = div;
  // Si la conversacion viene por voz, se puede contestar la
  // confirmacion hablando ("sí"/"no") en vez de tener que tocar un
  // boton - setComposerEnabled(false) de arriba deja el mic
  // deshabilitado como el resto del composer, asi que aca se reactiva
  // solo para este caso puntual.
  if (wasVoiceLoop) {
    micButtonForState.disabled = false;
    setTimeout(() => {
      if (!micButtonForState.classList.contains("recording")) micButtonForState.click();
    }, 500);
  }
}

function resolveConfirm(id, approved, bubbleEl) {
  sendMessage({ type: "tool_confirm_response", id, approved });
  bubbleEl.querySelector(".confirm-actions").remove();
  bubbleEl.classList.add(approved ? "confirm-resolved-yes" : "confirm-resolved-no");
  if (pendingConfirmId === id) {
    pendingConfirmId = null;
    pendingConfirmBubbleEl = null;
    setComposerEnabled(true);
  }
}

function connect() {
  ws = new WebSocket("ws://127.0.0.1:8731/ws/chat");

  ws.onopen = () => setAtlasState("listo");

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.type === "transcript") {
      if (pendingConfirmId) {
        // Con una confirmacion pendiente, lo que se acaba de hablar es
        // la respuesta a esa confirmacion (sí/no), no un mensaje nuevo -
        // el backend ya sabe no arrancar un turno en este caso (ver
        // core/app.py).
        addMessage(`🎙️ "${data.text}"`, "user");
        const approved = matchYesNo(data.text);
        if (approved === null) {
          addMessage("No entendí si es sí o no - ¿confirmás o cancelás?", "atlas");
          setTimeout(() => {
            if (!micButtonForState.classList.contains("recording")) micButtonForState.click();
          }, 400);
        } else {
          resolveConfirm(pendingConfirmId, approved, pendingConfirmBubbleEl);
        }
        return;
      }
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
      } else if (data.name === "stop_listening") {
        // El modelo detecto que el usuario ya no necesita nada mas - se
        // apaga el modo voz continuo sin mostrar una linea tecnica de
        // "Atlas usa: stop_listening()" en el chat, no aporta nada verlo.
        setVoiceLoopActive(false);
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
      setVoiceLoopActive(false);
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
  setVoiceLoopActive(false);
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
  // "Detener" ademas sirve como salida de emergencia del modo voz: si
  // el microfono esta escuchando, lo apaga (dispara stopRecording en
  // face.js) y se asegura de que no se vuelva a prender solo despues.
  if (micButtonForState.classList.contains("recording")) {
    setVoiceLoopActive(false);
    micButtonForState.click();
  }
  sendMessage({ type: "stop" });
});

// El estado "escuchando" se deriva observando la clase "recording" que
// face.js ya prende/apaga por su cuenta en el boton del mic - no se
// toca esa logica, solo se mira desde afuera. Este mismo observer
// tambien arma el modo voz continuo la primera vez que el usuario toca
// el mic, y prende/corta el detector de silencio (VAD) junto con cada
// grabacion real.
new MutationObserver(() => {
  const recording = micButtonForState.classList.contains("recording");
  if (recording) {
    if (!voiceLoopActive) setVoiceLoopActive(true);
    startVAD();
  } else {
    stopVAD();
  }
  // "Detener" antes solo se habilitaba con un turno en curso en el
  // servidor - mientras el mic estaba escuchando (todavia nada enviado)
  // se quedaba deshabilitado, sin ninguna forma visible de cortar la
  // escucha. Ahora tambien se habilita mientras esta grabando.
  stopButton.disabled = !(turnInFlight || recording);
  if (turnInFlight) return; // no pisar un estado de turno real en curso
  setAtlasState(recording ? "escuchando" : "listo");
}).observe(micButtonForState, { attributes: true, attributeFilter: ["class"] });

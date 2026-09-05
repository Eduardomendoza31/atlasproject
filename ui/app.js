// Orquestador de la interfaz nueva (Fase 6): sidebar, tabs, tarjetas
// flotantes, panel derecho, barra de accesos rapidos, modo voz. No sabe
// nada de websockets - reacciona a los eventos "atlas:state"/"atlas:tool"
// que dispara chat.js, y para actuar usa las mismas funciones que ya
// expone chat.js (sendMessage/input/form), nunca toca face.js.

const statusDot = document.getElementById("status-dot");
const statusText = document.getElementById("status-text");
const voicePanel = document.getElementById("voice-panel");
const cardsLeft = document.getElementById("cards-left");
const cardsRight = document.getElementById("cards-right");
const activityListEl = document.getElementById("activity-list");
const planListEl = document.getElementById("plan-list");
const agentsListEl = document.getElementById("agents-list");

const STATE_LABELS = {
  listo: "Listo para ayudarte",
  escuchando: "Escuchando…",
  procesando: "Procesando…",
  ejecutando: "Ejecutando tarea…",
  autorizacion: "Necesito tu autorización",
  hablando: "Hablando…",
  desconectado: "Reconectando…",
};

window.addEventListener("atlas:state", (e) => {
  const { state } = e.detail;
  statusText.textContent = STATE_LABELS[state] || state;
  statusDot.className = `status-dot status-${state}`;
  document.body.dataset.atlasState = state;
  voicePanel.hidden = state !== "escuchando";
});

// --- Tarjetas flotantes: rellenan/enfocan el campo de comando, nunca lo
// mandan solas (salvo el cambio de modo) - Atlas no debe "hacer algo"
// sin que el usuario haya dicho que, especificamente.
function primeInput(text) {
  input.value = text;
  input.focus();
  input.setSelectionRange(text.length, text.length);
}

const CARD_SETS = {
  general: [
    { icon: "🔎", label: "Investigar", run: () => primeInput("Investiga sobre ") },
    { icon: "📁", label: "Organizar archivos", run: () => primeInput("Ayúdame a organizar la carpeta ") },
    { icon: "💻", label: "Programar", run: () => renderCards("code") },
    { icon: "📄", label: "Crear documento", run: () => primeInput("Crea un archivo con ") },
    { icon: "🌐", label: "Buscar en internet", run: () => primeInput("Busca en internet ") },
  ],
  code: [
    { icon: "🔍", label: "Analizar código", run: () => primeInput("Lee y analiza el archivo ") },
    { icon: "🐛", label: "Buscar errores", run: () => primeInput("Ejecuta y revisa si hay errores en ") },
    { icon: "🔧", label: "Corregir", run: () => primeInput("Corrige el problema en ") },
    { icon: "▶", label: "Ejecutar", run: () => primeInput("Ejecuta el comando ") },
    { icon: "←", label: "Volver", run: () => renderCards("general") },
  ],
};

function renderCards(setName) {
  const cards = CARD_SETS[setName];
  cardsLeft.innerHTML = "";
  cardsRight.innerHTML = "";
  cards.forEach((card, i) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "action-card";
    btn.style.animationDelay = `${i * 0.05}s`;
    btn.innerHTML = `<span class="icon">${card.icon}</span><span>${card.label}</span>`;
    btn.addEventListener("click", card.run);
    (i % 2 === 0 ? cardsLeft : cardsRight).appendChild(btn);
  });
}

renderCards("general");

// --- Barra de accesos rapidos: mandan una instruccion en lenguaje
// natural, Atlas decide usar run_command (y el usuario confirma, como
// con cualquier herramienta critica) - no se salta el flujo existente.
const QUICK_PROMPTS = {
  explorer: "Abre el explorador de archivos de Windows.",
  terminal: "Abre una ventana de PowerShell.",
  browser: "Abre mi navegador de internet predeterminado.",
  notes: "Abre el Bloc de notas.",
};

function sendQuickPrompt(text) {
  if (turnInFlight) return;
  input.value = text;
  form.requestSubmit();
}

document.getElementById("quick-bar").addEventListener("click", (e) => {
  const btn = e.target.closest(".quick-btn");
  if (!btn) return;
  const prompt = QUICK_PROMPTS[btn.dataset.quick];
  if (prompt) sendQuickPrompt(prompt);
});

// --- Tabs de modo (Chat / Visual) ---
document.getElementById("mode-tabs").addEventListener("click", (e) => {
  const tab = e.target.closest(".mode-tab");
  if (!tab) return;
  document.querySelectorAll(".mode-tab").forEach((t) => t.classList.remove("active"));
  tab.classList.add("active");
  document.body.classList.toggle("mode-visual", tab.dataset.viewMode === "visual");
});

// --- Sidebar: "Inicio" es la vista real; el resto son honestos (o
// atajos a algo que si existe) hasta que tengan backend propio.
function flashPanel(titleText) {
  const panel = Array.from(document.querySelectorAll(".panel")).find(
    (p) => p.querySelector("h3")?.textContent.trim() === titleText
  );
  if (!panel) return;
  panel.scrollIntoView({ behavior: "smooth", block: "center" });
  panel.style.borderColor = "var(--accent)";
  setTimeout(() => { panel.style.borderColor = ""; }, 900);
}

const NAV_ACTIONS = {
  proyectos: () => addMessage("📁 Proyectos todavía no está construido.", "atlas"),
  skills: () => flashPanel("Skills"),
  automatizaciones: () => flashPanel("Automatizaciones"),
  archivos: () => sendQuickPrompt(QUICK_PROMPTS.explorer),
  memoria: () => flashPanel("Memoria"),
  herramientas: () => addMessage(
    "🛠 Herramientas disponibles: leer archivos, listar carpetas, escribir archivos, ejecutar comandos de PowerShell, y buscar en internet.",
    "atlas"
  ),
};

document.getElementById("sidebar-nav").addEventListener("click", (e) => {
  const item = e.target.closest(".nav-item");
  if (!item) return;
  document.querySelectorAll(".nav-item").forEach((n) => n.classList.remove("active"));
  item.classList.add("active");
  const action = NAV_ACTIONS[item.dataset.nav];
  if (action) action();
});

// --- Actividad reciente + plan del turno + "agentes activos" honesto,
// todo derivado de las mismas herramientas reales que ya corren.
const ACTIVITY_MAX = 20;
let activeToolLabel = null;

function addActivityEntry(text) {
  const empty = activityListEl.querySelector(".activity-empty");
  if (empty) empty.remove();
  const li = document.createElement("li");
  li.textContent = text;
  activityListEl.prepend(li);
  while (activityListEl.children.length > ACTIVITY_MAX) {
    activityListEl.removeChild(activityListEl.lastChild);
  }
}

function setAgentActivity(label) {
  activeToolLabel = label;
  if (!label) {
    agentsListEl.innerHTML = '<div class="agents-empty">Sin actividad</div>';
    return;
  }
  agentsListEl.innerHTML = `
    <div class="agent-item"><span class="agent-dot"></span><span>${label}</span></div>
  `;
}

function clearPlan() {
  planListEl.innerHTML = '<li class="plan-empty">Sin pasos todavía.</li>';
}

const planSteps = new Map();

function addPlanStep(id, name) {
  const empty = planListEl.querySelector(".plan-empty");
  if (empty) empty.remove();
  const li = document.createElement("li");
  li.textContent = `→ ${name}`;
  planListEl.appendChild(li);
  planSteps.set(id, li);
}

function completePlanStep(id, denied) {
  const li = planSteps.get(id);
  if (!li) return;
  li.classList.add(denied ? "denied" : "done");
  li.textContent = (denied ? "✗ " : "✓ ") + li.textContent.replace(/^[→✓✗]\s*/, "");
}

// Un envio nuevo (texto o accion rapida) empieza un turno nuevo: el plan
// de la pantalla es del turno actual, no un historial acumulado.
form.addEventListener("submit", () => clearPlan(), true);

window.addEventListener("atlas:tool", (e) => {
  const d = e.detail;
  if (d.phase === "call") {
    addActivityEntry(`🔧 ${d.name}`);
    addPlanStep(d.id, d.name);
    setAgentActivity(`Atlas — usando ${d.name}`);
  } else if (d.phase === "confirm") {
    addActivityEntry(`⏳ ${d.name} — esperando autorización`);
  } else if (d.phase === "result") {
    addActivityEntry(`${d.denied ? "❌" : "✅"} ${d.name}`);
    completePlanStep(d.id, d.denied);
    setAgentActivity(null);
  }
});

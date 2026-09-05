// Orquestador de la interfaz nueva (Fase 6): sidebar, tarjetas flotantes,
// panel derecho, barra de accesos rapidos, modo voz, modo inmersivo. No
// sabe nada de websockets - reacciona a los eventos "atlas:state"/
// "atlas:tool" que dispara chat.js, y para actuar usa las mismas
// funciones que ya expone chat.js (sendMessage/input/form), nunca toca
// face.js. Los iconos vienen de icons.js (Phosphor, SVG en linea).

const statusDot = document.getElementById("status-dot");
const statusText = document.getElementById("status-text");
const voicePanel = document.getElementById("voice-panel");
const cardsLeft = document.getElementById("cards-left");
const cardsRight = document.getElementById("cards-right");
const activityListEl = document.getElementById("activity-list");
const planListEl = document.getElementById("plan-list");
const agentsListEl = document.getElementById("agents-list");
const quickBarEl = document.getElementById("quick-bar");
const immersiveButton = document.getElementById("immersive-button");

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
    { key: "investigar", icon: "magnifying-glass", label: "Investigar", desc: "Busca y analiza información", run: () => primeInput("Investiga sobre ") },
    { key: "organizar", icon: "folder-simple", label: "Organizar archivos", desc: "Gestiona tus archivos", run: () => primeInput("Ayúdame a organizar la carpeta ") },
    { key: "programar", icon: "code", label: "Programar", desc: "Crea y depura código", run: () => renderCards("code") },
    { key: "documento", icon: "file-text", label: "Crear documento", desc: "Redacta y genera archivos", run: () => primeInput("Crea un archivo con ") },
    { key: "internet", icon: "globe", label: "Buscar en internet", desc: "Explora la web en vivo", run: () => primeInput("Busca en internet ") },
  ],
  code: [
    { key: "analizar", icon: "magnifying-glass", label: "Analizar código", desc: "Lee y revisa el archivo", run: () => primeInput("Lee y analiza el archivo ") },
    { key: "errores", icon: "bug", label: "Buscar errores", desc: "Detecta fallos reales", run: () => primeInput("Ejecuta y revisa si hay errores en ") },
    { key: "corregir", icon: "wrench", label: "Corregir", desc: "Aplica una solución", run: () => primeInput("Corrige el problema en ") },
    { key: "ejecutar", icon: "play", label: "Ejecutar", desc: "Corre un comando", run: () => primeInput("Ejecuta el comando ") },
    { key: "volver", icon: "arrow-left", label: "Volver", desc: "Vuelve al menú principal", run: () => renderCards("general") },
  ],
};

// Que tarjeta se ilumina cuando Atlas usa una herramienta real - solo se
// mapean los casos donde la relacion es honesta (1 a 1), no se inventan
// conexiones para herramientas que no calzan con ninguna tarjeta.
const TOOL_TO_CARD = {
  web_search: "internet",
  write_file: "documento",
  list_directory: "organizar",
  read_file: "analizar",
};

function renderCards(setName) {
  const cards = CARD_SETS[setName];
  cardsLeft.innerHTML = "";
  cardsRight.innerHTML = "";
  cards.forEach((card, i) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "action-card";
    btn.dataset.cardKey = card.key;
    btn.style.animationDelay = `${i * 0.06}s`;
    btn.style.setProperty("--float-delay", `${(i % 4) * -1.4}s`);
    btn.style.setProperty("--float-duration", `${6 + (i % 3)}s`);
    btn.innerHTML = `
      <span class="action-card-inner">
        <span class="action-card-top">
          <span class="icon">${icon(card.icon)}</span>
          <span class="action-card-arrow">${icon("arrow-right")}</span>
        </span>
        <span class="action-card-title">${card.label}</span>
        <span class="action-card-desc">${card.desc}</span>
      </span>`;
    btn.addEventListener("click", card.run);
    (i % 2 === 0 ? cardsLeft : cardsRight).appendChild(btn);
  });
}

renderCards("general");

// --- Barra de accesos rapidos: mandan una instruccion en lenguaje
// natural, Atlas decide usar run_command (y el usuario confirma, como
// con cualquier herramienta critica) - no se salta el flujo existente.
const QUICK_ACTIONS = [
  { key: "explorer", icon: "folder-simple", label: "Explorador", prompt: "Abre el explorador de archivos de Windows." },
  { key: "terminal", icon: "terminal-window", label: "Terminal", prompt: "Abre una ventana de PowerShell." },
  { key: "browser", icon: "compass", label: "Navegador", prompt: "Abre mi navegador de internet predeterminado." },
  { key: "notes", icon: "note", label: "Notas", prompt: "Abre el Bloc de notas." },
];

function sendQuickPrompt(text) {
  if (turnInFlight) return;
  input.value = text;
  form.requestSubmit();
}

QUICK_ACTIONS.forEach((qa) => {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "quick-btn";
  btn.title = qa.label;
  btn.innerHTML = `${icon(qa.icon)}<span class="quick-label">${qa.label}</span>`;
  btn.addEventListener("click", () => sendQuickPrompt(qa.prompt));
  quickBarEl.appendChild(btn);
});

// --- Modo inmersivo: oculta sidebar/panel/tarjetas para dejar solo el
// rostro y el comando, para cuando se quiere la pantalla mas despejada
// posible (util en modo voz o simplemente para mirar a Atlas).
immersiveButton.addEventListener("click", () => {
  const active = document.body.classList.toggle("mode-visual");
  immersiveButton.classList.toggle("active", active);
  immersiveButton.title = active ? "Salir del modo inmersivo" : "Modo inmersivo (solo rostro)";
});

// --- Sidebar: "Inicio" es la vista real; el resto son honestos (o
// atajos a algo que si existe) hasta que tengan backend propio.
function flashPanel(titleText) {
  const panel = Array.from(document.querySelectorAll(".panel")).find(
    (p) => p.querySelector("h3")?.textContent.trim() === titleText
  );
  if (!panel) return;
  panel.scrollIntoView({ behavior: "smooth", block: "center" });
  panel.classList.add("panel-flash");
  setTimeout(() => panel.classList.remove("panel-flash"), 900);
}

const NAV_ACTIONS = {
  proyectos: () => addMessage("Proyectos todavía no está construido.", "atlas"),
  skills: () => flashPanel("Skills"),
  automatizaciones: () => flashPanel("Automatizaciones"),
  archivos: () => sendQuickPrompt(QUICK_ACTIONS.find((q) => q.key === "explorer").prompt),
  memoria: () => flashPanel("Memoria"),
  herramientas: () => addMessage(
    "Herramientas disponibles: leer archivos, listar carpetas, escribir archivos, ejecutar comandos de PowerShell, y buscar en internet.",
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

function addActivityEntry(iconName, text, cls) {
  const empty = activityListEl.querySelector(".activity-empty");
  if (empty) empty.remove();
  const li = document.createElement("li");
  if (cls) li.className = cls;
  li.innerHTML = `<span class="entry-icon">${icon(iconName)}</span><span>${text}</span>`;
  activityListEl.prepend(li);
  while (activityListEl.children.length > ACTIVITY_MAX) {
    activityListEl.removeChild(activityListEl.lastChild);
  }
}

function setAgentActivity(label) {
  if (!label) {
    agentsListEl.innerHTML = '<div class="agents-empty">Sin actividad</div>';
    return;
  }
  agentsListEl.innerHTML = `<div class="agent-item"><span class="agent-dot"></span><span>${label}</span></div>`;
}

function clearPlan() {
  planListEl.innerHTML = '<li class="plan-empty">Sin pasos todavía.</li>';
}

const planSteps = new Map();

function addPlanStep(id, name) {
  const empty = planListEl.querySelector(".plan-empty");
  if (empty) empty.remove();
  const li = document.createElement("li");
  li.innerHTML = `<span class="entry-icon">${icon("arrow-left", "rotate-180")}</span><span>${name}</span>`;
  planListEl.appendChild(li);
  planSteps.set(id, li);
}

function completePlanStep(id, denied) {
  const li = planSteps.get(id);
  if (!li) return;
  li.classList.add(denied ? "denied" : "done");
  const label = li.querySelector("span:last-child").textContent;
  li.innerHTML = `<span class="entry-icon">${icon(denied ? "x" : "check-circle")}</span><span>${label}</span>`;
}

// Un envio nuevo (texto o accion rapida) empieza un turno nuevo: el plan
// de la pantalla es del turno actual, no un historial acumulado.
form.addEventListener("submit", () => clearPlan(), true);

function highlightCard(cardKey) {
  document.querySelectorAll(".action-card").forEach((btn) => {
    btn.classList.toggle("active-tool", !!cardKey && btn.dataset.cardKey === cardKey);
    btn.classList.toggle("dimmed", !!cardKey && btn.dataset.cardKey !== cardKey);
  });
}

// announce_plan/report_outcome son "meta" - anuncian intencion o cierran
// una tarea, no son una accion real sobre el computador. Se loguean en
// Actividad reciente con su propio icono, pero no ocupan un paso del
// checklist "Plan del turno actual" (ese panel es para las acciones
// reales que van pasando, no para el plan que el modelo declaro).
const META_TOOLS = new Set(["announce_plan", "report_outcome"]);

window.addEventListener("atlas:tool", (e) => {
  const d = e.detail;
  if (d.phase === "call") {
    if (d.name === "announce_plan") {
      addActivityEntry("compass", "Atlas anunció un plan");
      setAgentActivity("Atlas — planificando");
    } else if (d.name === "report_outcome") {
      const ok = d.arguments && d.arguments.success;
      addActivityEntry(ok ? "check-circle" : "warning", "Atlas informó el resultado", ok ? "done" : "pending");
      setAgentActivity(null);
    } else {
      addActivityEntry("wrench", d.name);
      addPlanStep(d.id, d.name);
      setAgentActivity(`Atlas — usando ${d.name}`);
      highlightCard(TOOL_TO_CARD[d.name]);
    }
  } else if (d.phase === "confirm") {
    addActivityEntry("warning", `${d.name} — esperando autorización`, "pending");
  } else if (d.phase === "result") {
    if (!META_TOOLS.has(d.name)) {
      addActivityEntry(d.denied ? "x" : "check-circle", d.name, d.denied ? "denied" : "done");
      completePlanStep(d.id, d.denied);
      setAgentActivity(null);
      highlightCard(null);
    }
  }
});

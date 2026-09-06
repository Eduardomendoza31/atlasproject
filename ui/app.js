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
  create_word_document: "documento",
  create_excel_document: "documento",
  create_pdf_document: "documento",
  create_powerpoint_document: "documento",
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
    // Si el espacio obliga a mostrar solo el icono (ver @container
    // cardrail en theme.css), el title nativo del boton sigue dejando
    // ver de que se trata al pasar el mouse.
    btn.title = `${card.label} - ${card.desc}`;
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

// --- Skills instaladas: reales, vienen del backend (core/skills.py).
// Si el fetch falla o no hay ninguna, se deja el estado honesto de
// "no hay skills" en vez de inventar una lista.
const skillsListEl = document.getElementById("skills-list");

async function loadSkills() {
  try {
    const res = await fetch("http://127.0.0.1:8731/skills");
    const data = await res.json();
    const skills = data.skills || [];
    if (skills.length === 0) {
      skillsListEl.innerHTML = '<li class="panel-empty">No hay skills instaladas todavía.</li>';
      return;
    }
    skillsListEl.innerHTML = "";
    skills.forEach((s) => {
      const li = document.createElement("li");
      li.className = "skill-item";
      li.innerHTML = `<span class="entry-icon">${icon("puzzle-piece")}</span><span><strong>${s.name}</strong><br><span class="skill-desc">${s.description}</span></span>`;
      skillsListEl.appendChild(li);
    });
  } catch {
    skillsListEl.innerHTML = '<li class="panel-empty">No hay skills instaladas todavía.</li>';
  }
}

loadSkills();

// --- Automatizaciones: reales, vienen del backend (core/automations.py).
// Se crean/administran conversando con Atlas (create_automation,
// list_automations, etc.) - este panel solo las muestra, no las edita.
const automationsListEl = document.getElementById("automations-list");

function describeSchedule(schedule) {
  if (!schedule) return "";
  if (schedule.type === "daily") return `Todos los días a las ${schedule.time || "08:00"}`;
  if (schedule.type === "weekly") return `Los ${schedule.weekday || "lunes"} a las ${schedule.time || "08:00"}`;
  if (schedule.type === "interval_minutes") return `Cada ${schedule.minutes || 60} min`;
  return "Horario personalizado";
}

async function loadAutomations() {
  try {
    const res = await fetch("http://127.0.0.1:8731/automations");
    const data = await res.json();
    const automations = data.automations || [];
    if (automations.length === 0) {
      automationsListEl.innerHTML = '<li class="panel-empty">No hay automatizaciones creadas. Pídele a Atlas que cree una.</li>';
      return;
    }
    automationsListEl.innerHTML = "";
    automations.forEach((a) => {
      const li = document.createElement("li");
      li.className = "skill-item";
      const statusIcon = a.enabled ? "check-circle" : "warning";
      li.innerHTML = `<span class="entry-icon">${icon(statusIcon)}</span><span><strong>${a.description}</strong><br><span class="skill-desc">${describeSchedule(a.schedule)} — ${a.enabled ? "activa" : "pausada"}</span></span>`;
      automationsListEl.appendChild(li);
    });
  } catch {
    automationsListEl.innerHTML = '<li class="panel-empty">No hay automatizaciones creadas. Pídele a Atlas que cree una.</li>';
  }
}

loadAutomations();

// --- Proyectos: reales, vienen de core/projects.py (SQLite). Se crean
// hablando con Atlas o con el formulario chico de aca abajo (que en el
// fondo manda el mismo mensaje de texto que si el usuario lo hubiera
// escrito - no hay un camino "directo" aparte, mismo criterio ya usado
// para Automatizaciones: todo pasa por el chat real). Cambiar de
// proyecto SI tiene un camino directo (switch_project por websocket,
// ver core/app.py) porque no modifica nada, solo cambia que
// conversacion se esta mirando.
const projectsListEl = document.getElementById("projects-list");
let activeProjectId = null;

async function loadProjects() {
  try {
    const res = await fetch("http://127.0.0.1:8731/projects");
    const data = await res.json();
    const projects = data.projects || [];
    if (projects.length === 0) {
      projectsListEl.innerHTML = '<li class="panel-empty">No hay proyectos creados todavía.</li>';
      return;
    }
    projectsListEl.innerHTML = "";
    projects.forEach((p) => {
      const li = document.createElement("li");
      li.className = "skill-item project-item" + (p.id === activeProjectId ? " active" : "");
      li.dataset.projectId = p.id;
      li.innerHTML = `<span class="entry-icon">${icon("folders")}</span><span><strong>${p.name}</strong>${p.description ? `<br><span class="skill-desc">${p.description}</span>` : ""}</span>`;
      li.addEventListener("click", () => {
        if (turnInFlight) return;
        sendMessage({ type: "switch_project", project_id: p.id });
      });
      projectsListEl.appendChild(li);
    });
  } catch {
    projectsListEl.innerHTML = '<li class="panel-empty">No hay proyectos creados todavía.</li>';
  }
}

loadProjects();

window.addEventListener("atlas:project", (e) => {
  activeProjectId = e.detail.id;
  loadProjects();
});

document.getElementById("new-project-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const nameInput = document.getElementById("new-project-name");
  const name = nameInput.value.trim();
  if (!name || turnInFlight) return;
  input.value = `Crea un proyecto llamado "${name}".`;
  form.requestSubmit();
  nameInput.value = "";
});

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

const TIER_LABEL = { safe: "🟢", sensitive: "🟡", critical: "🔴" };

async function showAvailableTools() {
  try {
    const res = await fetch("http://127.0.0.1:8731/tools");
    const data = await res.json();
    const tools = data.tools || [];
    if (tools.length === 0) {
      addMessage("No hay herramientas registradas todavía.", "atlas");
      return;
    }
    const lines = tools.map((t) => `${TIER_LABEL[t.tier] || "•"} ${t.name} — ${t.description}`);
    addMessage(`Herramientas disponibles (${tools.length}):\n${lines.join("\n")}`, "atlas");
  } catch {
    addMessage("No pude consultar la lista de herramientas ahora mismo.", "atlas");
  }
}

const NAV_ACTIONS = {
  proyectos: () => flashPanel("Proyectos"),
  skills: () => flashPanel("Skills"),
  automatizaciones: () => flashPanel("Automatizaciones"),
  archivos: () => sendQuickPrompt(QUICK_ACTIONS.find((q) => q.key === "explorer").prompt),
  memoria: () => flashPanel("Memoria"),
  herramientas: () => showAvailableTools(),
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

// Cuando una de estas termina bien, el panel "Automatizaciones" puede
// haber cambiado (se creo, se borro, o se activo/pauso una) - se vuelve
// a pedir la lista real en vez de dejar el panel desactualizado.
const AUTOMATION_TOOLS = new Set(["create_automation", "delete_automation", "set_automation_enabled"]);
const PROJECT_TOOLS = new Set(["create_project"]);

// Mientras un agente especializado esta trabajando (delegate_to_agent),
// sus propias llamadas a herramientas no deben pisar el cartel de
// "Agentes activos" que ya muestra su nombre - siguen apareciendo en el
// log de Actividad reciente igual, para no perder transparencia.
let activeSubagent = null;

window.addEventListener("atlas:subagent", (e) => {
  const d = e.detail;
  if (d.phase === "start") {
    activeSubagent = d.agent;
    addActivityEntry("compass", `Delegado en ${d.agent}`);
    setAgentActivity(`${d.agent} — trabajando`);
  } else {
    activeSubagent = null;
    addActivityEntry("check-circle", `${d.agent} completó su tarea`, "done");
    setAgentActivity(null);
  }
});

window.addEventListener("atlas:tool", (e) => {
  const d = e.detail;
  if (d.phase === "call") {
    if (d.name === "announce_plan") {
      addActivityEntry("compass", "Atlas anunció un plan");
      if (!activeSubagent) setAgentActivity("Atlas — planificando");
    } else if (d.name === "report_outcome") {
      const ok = d.arguments && d.arguments.success;
      addActivityEntry(ok ? "check-circle" : "warning", "Atlas informó el resultado", ok ? "done" : "pending");
      if (!activeSubagent) setAgentActivity(null);
    } else {
      addActivityEntry("wrench", d.name);
      addPlanStep(d.id, d.name);
      if (!activeSubagent) setAgentActivity(`Atlas — usando ${d.name}`);
      highlightCard(TOOL_TO_CARD[d.name]);
    }
  } else if (d.phase === "confirm") {
    addActivityEntry("warning", `${d.name} — esperando autorización`, "pending");
  } else if (d.phase === "result") {
    if (!META_TOOLS.has(d.name)) {
      addActivityEntry(d.denied ? "x" : "check-circle", d.name, d.denied ? "denied" : "done");
      completePlanStep(d.id, d.denied);
      if (!activeSubagent) setAgentActivity(null);
      highlightCard(null);
    }
    if (!d.denied && AUTOMATION_TOOLS.has(d.name)) {
      loadAutomations();
    }
    if (!d.denied && PROJECT_TOOLS.has(d.name)) {
      loadProjects();
    }
  }
});

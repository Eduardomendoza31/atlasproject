# ATLAS — Arquitectura Actual

> Generado por auditoría de código el 2026-09-07. Refleja el repositorio en su
> estado real (commit `5ff45f7`), no el plan ni la visión. No se modificó
> ningún archivo de código para producir este documento.

## 1. Qué es Atlas hoy

Una aplicación de escritorio para un solo usuario (Eduardo), en Windows,
escrita en Python. Es un **monolito modular de un solo proceso**: una ventana
PyQt6 embebe un navegador (QWebEngineView) que carga una UI local en HTML/JS
plano, y ese mismo proceso corre un servidor FastAPI en un hilo de fondo. No
hay separación cliente/servidor real — la "API" es interna al proceso, pensada
para que la UI le hable por WebSocket, no para ser consumida por otro cliente.

No existe autenticación, ni concepto de usuario/tenant, ni ningún control de
acceso: todo asume implícitamente "un usuario, esta PC". El servidor escucha
solo en `127.0.0.1:8731`.

## 2. Diagrama real (no aspiracional)

```
┌──────────────────────────────── PROCESO ÚNICO (python.exe) ────────────────────────────────┐
│                                                                                              │
│  ┌───────────────┐   QWebEngineView    ┌─────────────────────────────────────────────┐      │
│  │  shell/main.py│ ── carga file:// ──▶ │  ui/index.html + app.js + chat.js + face.js  │      │
│  │  (PyQt6 window)│                     │  (JS plano, sin framework, sin build step)    │      │
│  └───────┬───────┘                     └───────────────────┬────────────────────────┘      │
│          │ thread                                           │ WebSocket ws://127.0.0.1:8731  │
│          ▼                                                   ▼ /ws/chat                       │
│  ┌──────────────────────────────────────────────────────────────────────────────────────┐  │
│  │                         core/app.py  — FastAPI app                                     │  │
│  │  · /health /skills /tools /agents /automations /projects (REST, solo lectura)          │  │
│  │  · /ws/chat: recibe texto o audio, un asyncio.Task por turno                            │  │
│  │  · arranca scheduler_loop() (automations) al iniciar                                    │  │
│  └───────┬───────────────────┬────────────────┬───────────────┬───────────────┬──────────┘  │
│          │                   │                │               │               │              │
│          ▼                   ▼                ▼               ▼               ▼              │
│  ┌───────────────┐  ┌────────────────┐  ┌───────────┐  ┌─────────────┐ ┌──────────────┐     │
│  │ core/agent.py │  │ memory/cortex.py│  │core/voice.py│ │core/projects│ │core/automations│   │
│  │ run_agent_turn │  │ maybe_save /    │  │ transcribe/ │ │  .py (SQLite)│ │.py (scheduler) │   │
│  │ (loop tool-use)│  │ relevant_context│  │ synthesize  │ │  proyectos   │ │  loop cada 60s │   │
│  └───────┬───────┘  └────────┬────────┘  └─────┬──────┘  └─────────────┘ └──────────────┘     │
│          │                   │                  │                                              │
│          ▼                   ▼                  ▼                                              │
│  ┌───────────────┐  ┌─────────────────┐  ┌──────────────────────┐                              │
│  │core/tools.py  │  │ memory/store.py  │  │ subproceso aparte:    │                              │
│  │ + skills/*.py │  │ memory/semantic.py│ │ core/transcribe_cli.py│──▶ faster-whisper (LOCAL)   │
│  │ (registro de  │  │ (vault .md +      │  │ (Whisper, evita choque│                              │
│  │  herramientas)│  │  cache embeddings │  │  de runtime OMP)      │                              │
│  └───────┬───────┘  │  JSON en disco)   │  └──────────────────────┘                              │
│          │           └────────┬─────────┘                                                        │
│          │                    │                                                                   │
│          ▼                    ▼                                                                   │
│  ┌────────────────────────────────────────────┐        edge_tts.Communicate()                    │
│  │        core/providers.py (litellm)          │───────────────────────────────────┐              │
│  │  stream_reply / stream_agent_turn / complete│                                    │              │
│  │  / embed  — TODO pasa por litellm.acompletion│                                   │              │
│  └───────────────────┬──────────────────────────┘                                   │              │
└──────────────────────┼───────────────────────────────────────────────────────────────┼─────────────┘
                        │ HTTPS                                                          │ HTTPS
                        ▼                                                                ▼
         ┌─────────────────────────────┐                             ┌──────────────────────────────┐
         │   GOOGLE AI (Gemini API)     │                             │ Microsoft Edge TTS (cloud,    │
         │  gemini-3.5-flash-lite       │                             │ no documentado/no oficial)     │
         │  (chat, tools, visión,       │                             └──────────────────────────────┘
         │   cortex) + gemini-embedding │
         │   -001 (embeddings)          │
         └─────────────────────────────┘
                        ▲
                        │ (también, sin pasar por litellm)
         ┌─────────────────────────────┐
         │  ddgs (DuckDuckGo search)    │   web_search tool — HTTP directo, sin API key
         └─────────────────────────────┘
```

**Punto crítico de diseño:** no existe una capa `AIProvider`. `core/providers.py`
llama a `litellm.acompletion`/`litellm.aembedding` directamente con un string
de modelo (`gemini/gemini-3.5-flash-lite`) leído de `config/settings.json`.
litellm sí abstrae el *protocolo* (podría apuntar a Ollama, OpenAI, Anthropic,
etc. cambiando ese string), pero **nada en el código impide ni prepara** el
modo hídrido, el fallback local-primero, ni el registro de "se usó un proveedor
externo, por qué, con qué datos" que pide la visión del proyecto. Cambiar de
Gemini a un modelo local hoy = cambiar 3 strings en `settings.json` — pero el
comportamiento (reintentos, timeouts, si hace falta tools/visión) es idéntico
para cualquier modelo detrás de ese string, lo cual no siempre es cierto en la
práctica (modelos locales chicos manejan peor el function-calling).

## 3. Frontend

- `ui/index.html` + `ui/app.js` (orquestador del dashboard), `ui/chat.js`
  (WebSocket/mensajes/confirmaciones), `ui/face.js` (animación de la cara,
  protegida — ver memoria de fases), `ui/icons.js` (SVGs de Phosphor Icons
  embebidos inline), `ui/theme.css` / `ui/style.css`.
- Sin framework (no React/Vue/build step), scripts planos cargados por
  `<script>` compartiendo el `window` global. Cero dependencias de red en
  runtime para la UI (los iconos están embebidos, no vienen de un CDN).
- Se carga vía `file://` en la app real (QWebEngineView), o vía
  `python -m http.server` cuando se prueba en Chrome normal.

## 4. Backend

- **FastAPI** (`core/app.py`), un único módulo de rutas + el WebSocket
  `/ws/chat`, que es donde ocurre casi toda la lógica real de una conversación.
- Sin capas de "controlador/servicio/repositorio" — `core/app.py` hace de
  controlador y orquestador a la vez, llamando directo a `core/agent.py`,
  `memory/cortex.py`, `core/voice.py`, `core/projects.py`.
- **`core/agent.py`** es el loop de tool-use: llama al modelo, si pide una
  herramienta la ejecuta (o pide confirmación según el tier de riesgo:
  🟢 safe / 🟡 sensitive / 🔴 critical), le devuelve el resultado, repite
  (máx. 10 idas y vueltas). Soporta delegación a 4 "sub-agentes"
  especializados (`core/subagents.py`: Programador, Investigador, Documentos,
  Organizador) con su propio subconjunto de herramientas — patrón supervisor
  de un solo salto (no pueden delegar entre sí).
- **`core/tools.py`** es el registro central de herramientas (function
  calling). **`core/skills.py`** descubre automáticamente cualquier módulo en
  `skills/*.py` que exponga `register()` y lo carga al arrancar — así se
  agregan capacidades sin tocar el núcleo. Skills instaladas hoy: información
  del sistema, documentos de oficina (crear, no leer), automatizaciones,
  visión de pantalla, reglas aprendidas, orquestador (delegación),
  proyectos, WhatsApp (app de escritorio) y WhatsApp Web.

## 5. Base de datos / almacenamiento

Hay **tres mecanismos de persistencia distintos, sin unificar**:

1. **`memory/vault/*.md`** — archivos Markdown estilo Obsidian (frontmatter +
   `[[links]]`), uno por nota. Es la "memoria de largo plazo" (hechos
   aprendidos automáticamente por el cortex + reglas enseñadas
   explícitamente). Búsqueda por palabras (`memory/store.py`) y semántica
   (`memory/semantic.py`, embeddings vía Gemini con caché JSON en disco). Sin
   límite de tamaño, sin índice, se relee entero (`list_notes()`) en cada
   búsqueda — con 40 notas hoy no importa; no escala.
2. **`memory/atlas.db`** (SQLite) — proyectos, tareas y mensajes de
   conversación por proyecto (Fase 1 de "ATLAS V3", la más reciente).
   Esquema relacional real (`projects`, `messages`, `tasks`), sin `user_id`
   ni `tenant_id` todavía.
3. **`memory/automations.json`** — lista plana de automatizaciones
   programadas, reescrita entera en cada cambio.

No hay backups, no hay migración de esquema versionada, no hay política de
retención/borrado. `memory/vault/`, `atlas.db` y `automations.json` están en
`.gitignore` (correcto: son datos de usuario, no deberían ir al repo).

## 6. IA / modelos

Un único proveedor, **Google Gemini**, para las tres funciones que hoy usan
IA:

| Rol (`config/settings.json`) | Modelo | Uso |
|---|---|---|
| `conversational` | `gemini/gemini-3.5-flash-lite` | chat principal, tool-use, visión de pantalla, sub-agentes |
| `memory_cortex` | `gemini/gemini-3.5-flash-lite` | decide si guardar una nota nueva |
| `embeddings` | `gemini/gemini-embedding-001` | vectores para búsqueda semántica en el vault |

Todas las llamadas pasan por `litellm` (`core/providers.py`), con reintentos
manuales propios (no los de litellm) por la inestabilidad conocida de la capa
gratuita de Google. **No hay ningún modelo local ejecutándose para
generación/comprensión de lenguaje** — solo STT (Whisper, local) es IA
"local" hoy.

Voz:
- **STT**: `faster-whisper`, 100% local, corre en un subproceso Python aparte
  (`core/transcribe_cli.py`) para evitar un choque de runtime nativo
  (OpenMP) con Qt.
- **TTS**: `edge-tts`, que **NO es local** — es un cliente no oficial del
  servicio de voz de Microsoft Edge/Azure ("Read Aloud"), gratuito pero
  dependiente de que Microsoft siga exponiendo ese endpoint sin login. Es
  una dependencia externa real, aunque no aparece como tal a primera vista
  porque no pide API key.

## 7. Documentos — lo que existe y lo que NO

**Existe (generación, sentido único: Atlas → archivo):**
`skills/documents.py` crea `.docx`/`.xlsx`/`.pdf`/`.pptx` reales desde
contenido que el modelo genera (python-docx, openpyxl, reportlab,
python-pptx). Todo local, sin red.

**NO existe (lectura/ingesta, sentido Atlas ← archivo):**
- No hay pipeline de ingesta de documentos.
- `read_file` (`core/tools.py`) solo lee texto plano UTF-8 (falla en binario:
  un `.docx`/`.pdf` real se rechaza con "parece ser un archivo binario").
- No hay extracción de PDF, DOCX, HTML, CSV/XLSX, ni OCR.
- No hay segmentación (chunking), ni metadata de fragmento (documento,
  página, posición, hash, versión), ni forma de responder "¿de dónde
  sacaste esto?" con una cita real.
- El único camino para que Atlas "vea" contenido de un archivo no-texto es
  adjuntarlo como imagen en el chat (`core/app.py`, campo `attachment`) y
  que Gemini lo interprete multimodal — no hay indexación ni memoria de eso
  después del turno.

Es decir: **el área "leer y analizar documentos localmente" de la visión no
está construida todavía**, ni siquiera en su versión dependiente de la nube.

## 8. Búsqueda

Dos búsquedas totalmente independientes, sin relación entre sí:

1. **Búsqueda en la memoria (vault)**: por palabras clave
   (`memory/store.py::search_notes`, stemming crudo por truncado) y semántica
   (`memory/semantic.py::semantic_search`, coseno sobre embeddings de Gemini,
   sin ranking híbrido — se usa una u otra, con fallback a palabras si la
   semántica falla).
2. **Búsqueda en internet**: `web_search` (`core/tools.py`), vía `ddgs`
   (sucesor activo de `duckduckgo_search`), sin API key, resultado devuelto
   crudo al modelo (título + URL + snippet). No hay caché ni re-ranking.

No hay búsqueda sobre documentos (porque no hay ingesta), no hay búsqueda
híbrida (semántica + palabras combinadas con ranking), y ninguna búsqueda
respeta un futuro `user_id`/`tenant_id` (no existen todavía).

## 9. Memoria de Atlas — clasificación real vs. la visión

| Tipo pedido en la visión | ¿Existe? | Dónde |
|---|---|---|
| Memoria de usuario (preferencias) | Parcial | Reglas enseñadas (`skills/rules.py`), tag `regla` en el vault |
| Memoria conversacional | Parcial | Historial en RAM por conexión WebSocket (se pierde al cerrar) + historial persistente **solo si hay un proyecto activo** (`atlas.db`) |
| Memoria semántica (conocimiento) | Sí, básica | Notas del cortex (`memory/cortex.py`) + búsqueda semántica |
| Memoria documental | **No existe** | — (ver sección 7) |
| Memoria episódica (eventos/acciones) | **No existe** | Las automatizaciones registran `last_result` (un string), pero no hay un log de eventos/acciones consultable |

El "qué guardar / qué ignorar / qué actualizar / qué eliminar / qué necesita
confirmación" que pide la visión existe **solo para el caso de hechos
puntuales vs. reglas** (cortex guarda solo, reglas piden confirmación
explícita). No hay lógica de actualización (una nota nueva no reemplaza ni
corrige una vieja contradictoria) ni de eliminación controlada.

## 10. Herramientas / control del PC

`core/tools.py` + skills: `read_file`, `list_directory`, `write_file`,
`run_command` (PowerShell), `web_search`, `see_screen` (captura + Gemini
Vision), creación de documentos de oficina, WhatsApp (app de escritorio vía
`pywinauto`, o WhatsApp Web vía `selenium`), automatizaciones, reglas,
proyectos. Cada una tiene un tier de riesgo (🟢/🟡/🔴) que decide si se
autoejecuta o pide confirmación Sí/No al usuario (con audio de la pregunta
sintetizado en TTS). Sin sandboxing de rutas — decisión explícita de Eduardo,
la única barrera es la confirmación mostrando la ruta/comando exacto.

## 11. Flujo de una consulta (texto)

```
Usuario escribe/habla
  → (si es audio) core/voice.py::transcribe → subproceso Whisper local
  → core/app.py::chat() agrega el mensaje a `history`, lanza un asyncio.Task
  → memory/cortex.py::relevant_context()
      → reglas guardadas (siempre) + memory/semantic.py::semantic_search()
        → embeddings vía Gemini (red) → coseno contra caché en disco
  → core/agent.py::run_agent_turn()
      → core/providers.py::stream_agent_turn() → litellm.acompletion(stream=True)
        → GEMINI (red)
      → si pide una herramienta:
          - tier safe → se ejecuta directo
          - tier sensitive/critical → tool_confirm_request al frontend,
            espera un asyncio.Future, audio de la pregunta en paralelo (edge-tts, red)
      → resultado de la herramienta vuelve al modelo, se repite (máx. 10 vueltas)
  → texto final del turno
  → memory/cortex.py::maybe_save() en background (otra llamada a Gemini, red)
  → core/voice.py::synthesize() → edge-tts (red) → audio de vuelta al frontend
  → si hay proyecto activo: se persiste el intercambio en atlas.db
```

Cada turno normal, sin siquiera usar una herramienta, ya hace **como mínimo
3 llamadas de red a dos proveedores distintos** (Gemini para responder,
Gemini para decidir si guardar en memoria, Microsoft Edge para la voz) — nada
de esto funciona sin internet hoy, pese a que el "modo offline" es un
objetivo explícito de la visión.

## 12. Flujo de procesamiento de documentos

**No existe todavía** (ver sección 7). El único flujo real hoy es el inverso
(generación): `Petición del usuario → modelo decide contenido → skills/documents.py
→ archivo real en disco (.docx/.xlsx/.pdf/.pptx)`.

## 13. Autenticación / multiusuario

No existe autenticación de ningún tipo. El servidor confía en que solo el
propio proceso PyQt6 (o un desarrollador local) puede llegar a
`127.0.0.1:8731`. No hay concepto de sesión de usuario más allá de la
conexión WebSocket en sí. Ningún esquema de base de datos tiene `user_id` ni
`tenant_id` (ni `atlas.db`, ni el vault, ni `automations.json`) — construir
multiusuario hoy exigiría tocar cada uno de esos tres almacenes y, más
importante, decidir el modelo de aislamiento (fila por usuario, esquema por
usuario, base por usuario) antes de que crezcan más.

## 14. Duplicación / mantenibilidad / seguridad — hallazgos puntuales

- **Persistencia fragmentada** (sección 5): tres formatos de almacenamiento
  para conceptos que son todos "memoria" — dificulta razonar sobre backups,
  consistencia y, sobre todo, aislamiento multiusuario futuro.
- **Sin capa `AIProvider`**: cualquier lógica específica de un proveedor
  (parseo de tool_calls fragmentados de Gemini en `stream_agent_turn`,
  comentado explícitamente en el código como "Gemini manda los fragmentos...")
  vive mezclada con el loop genérico — acoplamiento directo a Gemini, no a
  una interfaz.
- **`DEEPSEEK_API_KEY` en `config/.env.example`**: variable declarada pero
  sin ningún código que la lea — configuración muerta, probable intento
  anterior de diversificar proveedor que no se completó.
- **`run_command` sin sandbox**: es una decisión consciente y documentada
  (no un descuido), pero es el mayor riesgo de seguridad del sistema tal
  como está — un usuario que aprueba una confirmación 🔴 sin leerla con
  atención le da a Atlas ejecución arbitraria de PowerShell con los permisos
  de su usuario de Windows. Aceptable para un asistente personal de un solo
  usuario avanzado; **inaceptable sin cambios para cualquier escenario
  SaaS/multiusuario**.
- **`edge-tts` no es local pese a no pedir API key** — riesgo de vendor
  lock-in silencioso: si Microsoft cierra ese acceso no oficial, la voz de
  salida deja de funcionar de un día para otro sin aviso.
- **Vault sin límite de crecimiento**: `list_notes()` relee y tokeniza todas
  las notas en cada búsqueda por palabras; `semantic_search` reembebe (una
  llamada de red) todo lo que no esté en caché. Funciona bien a la escala
  actual (40 notas); no está diseñado para escalar a miles.
- **CORS abierto (`allow_origins=["*"]`)**: razonado en un comentario del
  propio código como aceptable porque el server solo escucha en loopback —
  cierto hoy, pero es el tipo de configuración que hay que recordar
  endurecer *antes*, no después, de exponer Atlas a una red o a un servidor.
- **Sin tests automatizados**: no hay carpeta `tests/` en el repo. Toda la
  verificación documentada en el historial de fases fue manual
  (conversaciones reales, capturas de pantalla). Esto es razonable para el
  ritmo de desarrollo actual, pero es un bloqueo real para cualquier
  comparación objetiva "Gemini vs. modelo local" que pida la migración.

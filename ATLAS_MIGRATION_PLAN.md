# ATLAS — Plan de Migración

> Ninguna de estas fases se ha ejecutado. Este documento describe el plan
> propuesto para revisión, no trabajo ya hecho. Ver `ATLAS_TECHNOLOGY_DECISIONS.md`
> para la justificación técnica de cada elección referenciada aquí.

Principio que atraviesa todas las fases: **cada una debe dejar Atlas
funcionando de punta a punta**, nunca a medio romper. Ninguna fase depende de
eliminar Gemini — se desacopla primero (Fase 2) y se apaga gradualmente
después, nunca al revés.

---

### Fase 1 — Auditoría (esta fase)
- **Objetivo:** entender el sistema real antes de tocarlo.
- **Archivos afectados:** ninguno (solo lectura).
- **Dependencias:** ninguna.
- **Costo:** $0.
- **Riesgo:** ninguno.
- **Dificultad:** — (completada).
- **Beneficio:** todas las fases siguientes parten de hechos verificados en
  el código, no de suposiciones.
- **Rollback:** no aplica.

### Fase 2 — Desacoplar Google AI (capa `AIProvider`)
- **Objetivo:** que ningún módulo llame a `litellm`/Gemini directamente;
  todo pasa por una interfaz `AIProvider` con métodos equivalentes a los que
  ya existen en `core/providers.py` (`stream_reply`, `stream_agent_turn`,
  `complete`, `embed`). `GeminiProvider` es la primera implementación
  (envuelve el código actual, comportamiento idéntico); se agrega
  `LocalProvider` (Ollama) como segunda implementación, aunque todavía no
  se use por defecto.
- **Archivos afectados:** `core/providers.py` (se reorganiza, no se
  reescribe la lógica de reintentos), `core/config.py` (el `model_for_role`
  pasa a resolver también *qué provider*, no solo *qué modelo*), ningún
  cambio en `core/agent.py`/`core/app.py`/`memory/*.py` más allá de importar
  la nueva interfaz en vez de las funciones sueltas.
- **Dependencias:** ninguna nueva (litellm ya soporta Ollama como target).
- **Costo:** $0.
- **Riesgo:** bajo — es una refactorización de forma, no de comportamiento;
  se verifica con las mismas conversaciones reales que ya funcionan hoy.
- **Dificultad:** media (hay que aislar con cuidado el parseo de
  `tool_calls` fragmentados, que hoy está documentado como específico de
  cómo Gemini los entrega).
- **Beneficio:** habilita todo lo que sigue sin volver a tocar esta capa.
- **Rollback:** trivial — es la misma lógica, reorganizada; revertir el
  commit no pierde nada.

### Fase 3 — Sistema local de documentos (ingesta)
- **Objetivo:** pipeline real Archivo → Identificación → Extracción → OCR si
  hace falta → Limpieza → Segmentación → Metadata, sin todavía conectarlo a
  embeddings (eso es la Fase 4). Cubre el hueco descrito en la sección 7 de
  `ATLAS_CURRENT_ARCHITECTURE.md`.
- **Archivos afectados:** nuevo módulo `core/documents/` (extractors por
  tipo: pdf, docx, xlsx, html, txt/md, imagen+OCR), nueva skill
  `skills/document_ingest.py` que expone una herramienta `import_document`.
- **Dependencias nuevas:** `pypdf` o `pdfplumber`, `beautifulsoup4`,
  `pytesseract` + binario de Tesseract (instalación de sistema, no solo pip),
  `pdf2image` (requiere Poppler instalado). **Nota de recursos:** Tesseract y
  Poppler son binarios nativos, no paquetes pip puros — hay que documentar
  su instalación en Windows (o empaquetarlos con el instalador final).
- **Costo:** $0.
- **Riesgo:** bajo-medio (parsers de formatos reales de usuarios variados
  siempre tienen casos borde: PDFs con capas raras, Excel con fórmulas,
  etc. — mitigado con manejo de errores por archivo, no por lote entero).
- **Dificultad:** media.
- **Beneficio:** directo — es el área de la visión que hoy no existe en
  absoluto.
- **Rollback:** fácil — es aditivo, ningún código existente lo usa todavía.

### Fase 4 — Embeddings locales
- **Objetivo:** reemplazar `gemini-embedding-001` por un modelo local
  (Qwen3-Embedding-0.6B vía Ollama, ver decisión técnica) detrás de la misma
  interfaz `AIProvider.embed()` de la Fase 2.
- **Archivos afectados:** `memory/semantic.py` (cambia solo qué provider
  usa, no la lógica de coseno/caché), `config/settings.json` (rol
  `embeddings` apunta a `ollama/qwen3-embedding` en vez de Gemini).
- **Dependencias nuevas:** Ollama instalado localmente (una sola vez,
  fuera de pip).
- **Costo:** $0.
- **Riesgo:** bajo — cambio acotado a un único archivo de lógica, con
  fallback disponible (volver a apuntar el rol a Gemini si algo falla).
- **Dificultad:** baja.
- **Beneficio:** saca la búsqueda semántica del camino de red — funciona
  offline desde este punto.
- **Rollback:** cambiar una línea en `settings.json`.

### Fase 5 — Base de conocimiento (esquema + almacenamiento vectorial)
- **Objetivo:** extender `memory/atlas.db` (SQLite, ya existe el patrón en
  `core/projects.py`) con tablas para documentos y fragmentos, con
  `sqlite-vec` para los vectores, y **`user_id`/`tenant_id` en cada tabla
  desde el día uno** (valen "local"/"eduardo" hoy, sin usarse todavía para
  filtrar nada — solo para no tener que rediseñar el esquema en la Fase 12).
  Reemplaza la caché JSON de embeddings de `memory/semantic.py` por estas
  tablas, unificando vault de notas + documentos bajo un mismo esquema de
  búsqueda.
- **Archivos afectados:** `memory/store.py`/`memory/semantic.py` (migran de
  archivos Markdown sueltos + JSON a tablas SQLite — con un script de
  migración de las notas existentes, no se pierden), `core/documents/`
  (Fase 3) pasa a escribir acá en vez de a ningún lado.
- **Dependencias nuevas:** `sqlite-vec` (extensión, se carga en Python vía
  `sqlite3.enable_load_extension`).
- **Costo:** $0.
- **Riesgo:** medio — es una migración de datos real (las notas del vault
  actual deben conservarse); se hace con un script de una sola vía que lee
  el vault viejo y lo vuelca a las tablas nuevas, verificado contando notas
  antes/después.
- **Dificultad:** media-alta.
- **Beneficio:** una sola base para notas + documentos + sus vectores, listo
  para migrar a Postgres+pgvector en la Fase 13 con el mismo esquema de
  columnas.
- **Rollback:** el vault en Markdown puede mantenerse como backup de lectura
  durante la transición; si algo falla, se sigue leyendo de ahí.

### Fase 6 — RAG local
- **Objetivo:** el flujo completo Consulta → Normalización → Búsqueda
  híbrida (semántica + palabras clave con ranking combinado, no "una u
  otra" como hoy) → Contexto relevante con cita de fuente (documento,
  página, fragmento) → Modelo local → Respuesta con fuentes.
- **Archivos afectados:** `memory/cortex.py::relevant_context` se extiende
  para incluir fragmentos de documentos (no solo notas), nueva función de
  ranking híbrido, el `system_prompt` (`core/app.py`) se instruye a citar
  la fuente cuando responde con contexto documental.
- **Dependencias nuevas:** ninguna (usa lo construido en Fases 3-5).
- **Costo:** $0.
- **Riesgo:** medio — el ranking híbrido bien hecho es la parte más
  delicada técnicamente de todo el plan; se evalúa con el set de preguntas
  de la estrategia de pruebas (ver más abajo) antes de darlo por bueno.
- **Dificultad:** alta.
- **Beneficio:** es el corazón de "consultar su propia base de
  conocimiento" — sin esto, la Fase 3-5 son solo almacenamiento sin uso real.
- **Rollback:** el modo actual (memoria de notas sin documentos) sigue
  disponible si se desactiva la extensión.

### Fase 7 — Modelo local para conversación
- **Objetivo:** activar por defecto el `LocalProvider` (Fase 2) para el rol
  `conversational` en casos donde no se necesite tool-use complejo ni
  visión, con fallback automático a Gemini cuando el modelo local no pueda
  (modo híbrido, ver más abajo).
- **Archivos afectados:** `core/agent.py` (lógica de "¿puedo responder
  localmente?" antes de decidir el provider), `config/settings.json`.
- **Dependencias nuevas:** ninguna adicional a la Fase 4 (mismo Ollama).
- **Costo:** $0.
- **Riesgo:** medio — la calidad de tool-use de un modelo de ~4B es
  notablemente inferior a Gemini; requiere pruebas reales con el set de
  evaluación antes de activarlo por defecto para todo.
- **Dificultad:** alta.
- **Beneficio:** es el paso que más reduce la dependencia real de Gemini.
- **Rollback:** volver `conversational` a apuntar a Gemini en `settings.json`.

### Fase 8 — Memoria (unificación de tipos)
- **Objetivo:** implementar los 5 tipos de memoria de la visión de forma
  explícita (usuario, conversacional, semántica, documental, episódica),
  con reglas claras de qué se guarda automático, qué pide confirmación, y
  qué se puede actualizar/eliminar — hoy solo existe la distinción
  hecho-automático vs. regla-confirmada.
- **Archivos afectados:** `memory/cortex.py` (se le agrega evaluación de
  contradicción — si una nota nueva contradice una vieja, se marca en vez
  de duplicar), nuevo log de eventos para memoria episódica (tabla en
  `atlas.db` de la Fase 5, no un archivo nuevo).
- **Dependencias nuevas:** ninguna.
- **Costo:** $0.
- **Riesgo:** bajo-medio.
- **Dificultad:** media.
- **Beneficio:** memoria más confiable y auditable ("¿por qué Atlas cree
  esto?" siempre tiene una respuesta con fuente/fecha/confianza).
- **Rollback:** aditivo sobre el esquema de la Fase 5.

### Fase 9 — Aprendizaje controlado
- **Objetivo:** formalizar el flujo Información nueva → Evaluación (¿es
  nueva? ¿relevante? ¿confiable? ¿contradictoria?) → Guardar → Relacionar →
  Indexar, con `source`/`confidence`/`timestamp`/`version`/`provenance`/
  `user_id` en cada nota — explícitamente **sin** fine-tuning de pesos del
  modelo, tal como pide la visión.
- **Archivos afectados:** `memory/cortex.py`, esquema de la Fase 5/8
  (columnas nuevas).
- **Dependencias nuevas:** ninguna.
- **Costo:** $0.
- **Riesgo:** bajo.
- **Dificultad:** media.
- **Beneficio:** memoria versionada y con procedencia, requisito para
  cualquier auditoría futura (incluida una eventual necesidad de
  cumplimiento de privacidad en SaaS).
- **Rollback:** aditivo.

### Fase 10 — Modo offline
- **Objetivo:** un modo explícito (config o comando) donde Atlas rechaza
  toda llamada de red (Gemini, edge-tts, ddgs) y usa solo modelo local,
  Piper TTS, memoria y documentos locales.
- **Archivos afectados:** `core/config.py` (flag `OFFLINE_MODE`),
  `core/providers.py` (el `AIProvider` local se vuelve obligatorio, no
  fallback), `core/voice.py` (Piper reemplaza a edge-tts — ver Fase 11 si se
  separa), `core/tools.py` (`web_search` se deshabilita o avisa que no está
  disponible).
- **Dependencias nuevas:** Piper TTS (ver Fase 11, puede adelantarse acá si
  conviene hacerlas juntas).
- **Costo:** $0.
- **Riesgo:** bajo.
- **Dificultad:** media.
- **Beneficio:** cumple directamente el objetivo 2 de la misión
  ("progresivamente sin depender de APIs externas").
- **Rollback:** apagar el flag.

### Fase 11 — Reemplazo de TTS (Piper)
- **Objetivo:** sacar la única dependencia de red que queda en el camino de
  salida de voz.
- **Archivos afectados:** `core/voice.py::synthesize` (única función a
  cambiar; su contrato — texto in, bytes de audio out — no cambia).
- **Dependencias nuevas:** Piper TTS + modelo de voz en español (descarga
  única, ~50-100 MB).
- **Costo:** $0.
- **Riesgo:** bajo — cambio aislado a una función.
- **Dificultad:** baja.
- **Beneficio:** completa el modo offline de la Fase 10; elimina el riesgo
  de lock-in silencioso de edge-tts (`ATLAS_EXTERNAL_DEPENDENCIES.md`).
- **Rollback:** volver a `edge_tts.Communicate(...)` en la misma función.

### Fase 12 — Dockerización (opcional, acotada)
- **Objetivo:** `docker compose up` para levantar **solo** Postgres cuando
  se lo adopte (Fase 13) — no para empaquetar toda la app de escritorio, que
  sigue corriendo nativa. Evaluar en este punto si además conviene
  containerizar Ollama (opcional, no obligatorio: Ollama ya corre nativo
  bien en Windows).
- **Archivos afectados:** nuevo `docker-compose.yml` (solo DB, y
  opcionalmente Ollama).
- **Dependencias nuevas:** Docker Desktop (solo si el usuario elige este
  camino en vez de instalar Postgres nativo en Windows).
- **Costo:** $0.
- **Riesgo:** bajo.
- **Dificultad:** baja.
- **Beneficio:** reproducibilidad del entorno de base de datos entre
  máquinas, paso natural antes de un servidor real.
- **Rollback:** seguir con SQLite si Postgres no se adopta todavía (ver
  Fase 13, es la que decide el "cuándo").

### Fase 13 — Preparación multiusuario + migración a PostgreSQL/pgvector
- **Objetivo:** migrar el esquema de la Fase 5/8/9 (ya diseñado con
  `user_id`/`tenant_id`) de SQLite a PostgreSQL + pgvector, y empezar a usar
  esas columnas de verdad para filtrar/aislar (aunque siga habiendo un solo
  usuario real operando la instancia).
- **Archivos afectados:** capa de acceso a datos (que para entonces debería
  ya estar aislada en `memory/`/`core/` detrás de funciones, no SQL disperso
  por todo el código — si no lo está, esta fase incluye ese aislamiento
  primero), script de migración de datos SQLite → Postgres.
- **Dependencias nuevas:** `psycopg` (driver Postgres), `pgvector` (extensión
  de Postgres) — Postgres mismo vía Docker (Fase 12) o instalación nativa.
- **Costo:** $0 en desarrollo (Postgres es gratis; un Postgres gestionado en
  la nube sería `OPCIONAL — FUTURO`, solo al desplegar a servidor real).
- **Riesgo:** medio-alto — es la primera vez que se toca el motor de
  persistencia entero; se mitiga porque el esquema ya nació pensado para
  esto (Fase 5), no se está improvisando un rediseño bajo presión.
- **Dificultad:** alta.
- **Beneficio:** habilita de verdad multiusuario y servidor — es el punto
  de no retorno hacia SaaS.
- **Rollback:** mantener el dump de SQLite hasta confirmar la migración con
  datos reales; posibilidad de operar en modo dual mientras se verifica.

### Fase 14 — Preparación para servidor
- **Objetivo:** separar `core/app.py` en un servicio desplegable
  independientemente del shell de PyQt6 (que pasa a ser un cliente más,
  no el único). Introducir autenticación real (hoy no existe ninguna).
- **Archivos afectados:** `shell/main.py` deja de lanzar el servidor en un
  hilo propio y se conecta a una instancia de API que puede ser local o
  remota; `core/app.py` gana middleware de autenticación.
- **Dependencias nuevas:** una librería de auth (a decidir en su momento —
  no se recomienda una ahora, sería adelantarse sin necesidad real).
- **Costo:** $0 en desarrollo.
- **Riesgo:** alto — es un cambio de forma de despliegue, no solo de código.
- **Dificultad:** alta.
- **Beneficio:** Atlas deja de estar atado a "una PC, un proceso".
- **Rollback:** el modo actual (todo en un proceso) puede coexistir como
  "modo desktop standalone" indefinidamente si el servidor no se necesita.

### Fase 15 — SaaS
- **Objetivo:** multi-tenancy real, facturación, aislamiento verificado
  entre usuarios, panel de administración. **No se detalla más aquí** —
  depende de decisiones de negocio (modelo de precios, hosting) que exceden
  el alcance de esta auditoría técnica.
- **Costo:** este es el primer punto del plan donde aparecen costos reales
  de infraestructura (hosting, no development). Marcar explícitamente como
  `OPCIONAL — FUTURO` hasta que exista una decisión de negocio de lanzar.

---

## Estrategia de pruebas (a construir antes de tocar código de producción)

Antes de Fase 7 (activar modelo local por defecto) hace falta poder comparar
objetivamente Gemini vs. modelo local, en vez de decidir por impresión. Se
propone `tests/evaluation/` con:

- Un set fijo de ~20-30 preguntas representativas en español, cubriendo:
  preguntas simples, preguntas que requieren memoria guardada, preguntas que
  requieren una herramienta (leer archivo, listar carpeta), preguntas que
  requieren varios pasos (plan→ejecutar→verificar), y preguntas sobre un
  documento importado (una vez exista la Fase 3-6).
- Cada pregunta con su respuesta esperada o criterio de aceptación (no
  siempre texto exacto — a veces "¿llamó a la herramienta correcta?" o
  "¿citó la fuente correcta?").
- Métricas a registrar por corrida: modelo usado, tiempo de respuesta, uso
  de RAM/CPU durante la respuesta (via `psutil`, ya es una dependencia
  existente), si la respuesta fue correcta, si usó la herramienta esperada.
- Esto no se construye en esta fase de auditoría (sería "código nuevo
  innecesario" antes de que exista qué comparar) — se deja documentado como
  entregable de arranque de la Fase 7.

## Estimación de recursos (esta máquina)

| Componente | RAM en reposo | RAM en uso activo |
|---|---|---|
| Atlas actual (PyQt6 + FastAPI + Whisper cargado) | ~300-500 MB | ~600 MB-1 GB durante transcripción |
| + Ollama con Qwen3 4B (Q4_K_M) cargado | +~200 MB (proceso Ollama) | +~3-4 GB mientras genera |
| + Ollama sirviendo embeddings (0.6B) | +~150 MB si se mantiene cargado | — |
| + Postgres (si/cuando se adopte, Fase 13) | +~100-150 MB | — |

Con 11.7 GB de RAM total, correr Atlas + modelo conversacional local +
embeddings local simultáneamente es viable (~5-6 GB pico), dejando margen
para el resto del sistema operativo y el navegador Chrome de pruebas — pero
es **el límite razonable** en esta máquina: no hay margen para además correr
un modelo de 8B+ o Postgres pesado al mismo tiempo sin notar lentitud.

## Riesgos transversales

- **Licencia de PyQt6 (GPL v3)** — riesgo legal real antes de comercializar
  (ver `ATLAS_TECHNOLOGY_DECISIONS.md`); no es parte de ninguna fase de
  arriba a propósito, se marca aparte porque conviene resolverlo temprano
  y es independiente del resto del plan (se puede migrar a PySide6 en
  paralelo, en cualquier momento).
- **Calidad de tool-use en modelos locales chicos** — es el riesgo técnico
  más grande de todo el plan (Fase 7). Se mitiga manteniendo Gemini como
  fallback indefinidamente, no como algo "a eliminar en la Fase X".
- **Vault/memoria sin backups hoy** — cualquier fase que toque
  `memory/atlas.db` o el vault debe empezar por hacer una copia, no dar por
  sentado que se puede recuperar si algo sale mal.

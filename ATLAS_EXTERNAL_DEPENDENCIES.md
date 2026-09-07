# ATLAS — Mapa de Dependencias Externas

> Clasificación: **A-Crítica** (Atlas no funciona sin ella hoy) · **B-Reemplazable**
> (sustituible por alternativa local) · **C-Opcional** (solo mejora una función)
> · **D-Innecesaria** (se puede eliminar).

## A — CRÍTICAS

### Google Gemini API (`gemini/gemini-3.5-flash-lite`, `gemini-embedding-001`)
- **Función:** chat principal, tool-use, visión de pantalla, decisión del
  cortex de memoria, embeddings de búsqueda semántica. Es el único "cerebro"
  de Atlas hoy.
- **Costo:** capa gratuita de Google AI Studio (con límites de cuota/rate,
  de ahí la lógica de reintentos manual en `core/providers.py`). Sin costo
  fijo hoy, pero sin garantía de que la capa gratuita se mantenga igual.
- **Necesita Internet:** sí, siempre.
- **Dependencia de API/clave:** sí (`GEMINI_API_KEY` en `.env`).
- **Riesgo de vendor lock-in:** **alto** — es el único proveedor de
  inteligencia de todo el sistema; sin `core/providers.py` abstrayendo un
  contrato `AIProvider` propio, cualquier cambio de Google (deprecación de
  modelo, cambio de límites, cambio de precio) afecta el 100% de la
  inteligencia de Atlas al mismo tiempo.
- **Alternativa local:** modelo pequeño vía Ollama/llama.cpp (ver
  `ATLAS_TECHNOLOGY_DECISIONS.md`) para conversación y cortex; embeddings
  locales (BGE-M3, Qwen3-Embedding, nomic-embed-text) para búsqueda semántica.
- **Alternativa open-source:** las de arriba, todas con pesos abiertos y
  licencia comercial permisiva.
- **Dificultad de reemplazo:** **media** — litellm ya abstrae el transporte
  (cambiar el string de modelo es trivial), pero el comportamiento de
  function-calling/tool-use de un modelo local de 3-8B es notablemente peor
  que Gemini, y la visión de pantalla (multimodal) hoy depende de que el
  modelo pueda ver imágenes, algo que no todos los modelos locales chicos
  hacen bien. El reemplazo real requiere la capa `AIProvider` + modo híbrido
  (Fase 2 del plan de migración), no solo cambiar el modelo.
- **Impacto de eliminarla hoy sin reemplazo:** Atlas deja de poder conversar,
  usar herramientas o buscar en memoria — quedaría reducido a transcribir
  voz y sintetizar audio sin nada que decir.

### litellm (librería)
- **Función:** capa de transporte hacia Gemini (y, si se configura, hacia
  cualquier otro proveedor/modelo local compatible).
- **Costo:** gratis, open source (MIT).
- **Necesita Internet:** no por sí misma (depende del proveedor detrás).
- **Riesgo de vendor lock-in:** bajo — es en sí misma la pieza que reduce
  lock-in, siempre que el resto del código no asuma comportamientos
  específicos de un proveedor (hoy `stream_agent_turn` sí tiene lógica
  documentada como específica de cómo Gemini fragmenta `tool_calls`).
- **Alternativa:** llamar cada API directo (más trabajo, más lock-in), o un
  `AIProvider` propio más fino sobre menos superficie.
- **Dificultad de reemplazo:** baja, es la pieza más fácil de mantener.

### PyQt6 / PyQt6-WebEngine
- **Función:** la ventana de escritorio y el motor que renderiza la UI HTML.
- **Costo:** PyQt6 es GPL v3 **o** licencia comercial de pago (Riverbank
  Computing) — **esto es una señal a atender**: GPL v3 en un producto que se
  planea vender como SaaS/comercial puede obligar a licenciar comercialmente
  PyQt6 (pago) o a migrar a una alternativa con licencia más permisiva
  (PySide6, que es LGPL, del propio proyecto Qt) antes de comercializar.
  **Ver `ATLAS_TECHNOLOGY_DECISIONS.md` — riesgo de licencia real, no solo
  técnico.**
- **Necesita Internet:** no.
- **Riesgo de vendor lock-in:** medio (por licencia, no por API — PySide6 es
  casi un reemplazo directo).
- **Alternativa:** PySide6 (misma base Qt, licencia LGPL, comercialmente más
  segura).
- **Dificultad de reemplazo:** baja-media (misma API de Qt en general, pero
  hay que revisar cada import `PyQt6.*` → `PySide6.*` y las diferencias de
  señales/slots que PySide6 maneja distinto en algunos casos).

### FastAPI / uvicorn / websockets
- **Función:** servidor backend interno, WebSocket de chat.
- **Costo:** gratis (MIT/BSD).
- **Necesita Internet:** no (loopback).
- **Riesgo de vendor lock-in:** bajo, estándar de facto en Python async,
  gran comunidad, mantenido activamente.
- **Alternativa:** ninguna necesaria — esta es una elección sólida para
  migrar a servidor sin reescritura.

### faster-whisper
- **Función:** transcripción de voz a texto (STT), 100% local.
- **Costo:** gratis, MIT.
- **Necesita Internet:** no.
- **Riesgo de vendor lock-in:** bajo.
- **Nota:** ya cumple el principio "local-first" de la visión. Mantener.

## B — REEMPLAZABLES (por algo local)

### edge-tts
- **Función:** texto a voz (TTS).
- **Costo:** gratis, pero es un cliente **no oficial** de un servicio cloud
  de Microsoft (no hay SLA, ni garantía de continuidad).
- **Necesita Internet:** **sí** — pese a no requerir API key, esto rompe el
  "modo offline" cada vez que Atlas habla.
- **Riesgo de vendor lock-in:** medio-alto — depende de un endpoint no
  documentado oficialmente; Microsoft podría bloquear el acceso sin aviso.
- **Alternativa local:** Piper TTS (rápido, CPU, voces en español
  disponibles, MIT), Coqui-TTS/XTTS (mejor calidad, más pesado) o
  `pyttsx3`/SAPI de Windows (calidad menor, sin dependencia de red ni de
  librería extra, ya viene con Windows).
- **Dificultad de reemplazo:** baja-media — `core/voice.py::synthesize()`
  es una función aislada de una sola responsabilidad; cambiar el motor no
  toca el resto del sistema.
- **Impacto de eliminarla:** ninguno grave si se reemplaza por Piper; alto
  si Microsoft corta el acceso antes de reemplazarla.

### Embeddings de Gemini (`gemini-embedding-001`)
- Cubierto como parte de la entrada "Google Gemini API" arriba, pero
  técnicamente es la pieza más fácil de las tres de separar primero: un
  modelo de embeddings local (BGE-M3, Qwen3-Embedding-0.6B, nomic-embed-text)
  vía Ollama o `sentence-transformers`/`fastembed` no necesita function
  calling ni visión — es el reemplazo de menor riesgo y mayor beneficio
  inmediato (saca la búsqueda semántica de memoria del camino crítico de
  red).

### ddgs (búsqueda web)
- **Función:** `web_search`, resultados de DuckDuckGo sin API key.
- **Costo:** gratis.
- **Necesita Internet:** sí, por definición (es una herramienta de
  *búsqueda en internet*, no debería ni tiene sentido volverse local — la
  propia visión del proyecto pide "Internet como fuente, no como cerebro").
  Se clasifica B solo en el sentido de que Atlas podría funcionar sin ella
  en modo offline (área 5 de la visión es explícitamente opcional según
  disponibilidad de red), no porque debiera reemplazarse por algo local.
- **Riesgo de vendor lock-in:** bajo — hay múltiples paquetes equivalentes
  (`duckduckgo_search` de donde viene, Brave Search API, SearXNG
  autoalojado si se quiere más control).
- **Alternativa:** SearXNG autoalojado (metabuscador open source) si se
  quiere evitar depender de un único paquete de terceros.

## C — OPCIONALES (mejoran una función, no son requisito)

### mediapipe + opencv-contrib-python
- **Función:** generación offline (no en runtime) de los sprites de la cara
  animada (`core/face_gen.py`), corrido manualmente una vez por asset, no en
  cada arranque.
- **Costo:** gratis, Apache 2.0 (mediapipe) / Apache 2.0 (opencv).
- **Necesita Internet:** no.
- **Riesgo:** bajo, es una herramienta de build de assets, no una
  dependencia de runtime del producto final.

### pywinauto / selenium
- **Función:** automatización de WhatsApp de escritorio (`pywinauto`) y
  WhatsApp Web (`selenium`).
- **Costo:** gratis, ambos BSD/Apache.
- **Necesita Internet:** selenium sí (controla un navegador que navega a
  WhatsApp Web); pywinauto no.
- **Riesgo de vendor lock-in:** bajo técnicamente, pero **riesgo de producto
  real**: automatizar WhatsApp Web puede violar sus términos de servicio y
  exponer la cuenta del usuario a restricciones — ya está señalado en el
  propio system prompt de Atlas, que exige preguntar al usuario cuál de las
  dos prefiere. Correcto tratarlo con cautela; no es un problema de
  arquitectura sino de política de uso.

### python-docx / openpyxl / reportlab / python-pptx / Pillow
- **Función:** generación de documentos de oficina.
- **Costo:** gratis (MIT/BSD, reportlab es BSD-style con opción comercial
  para soporte, no requerida).
- **Necesita Internet:** no.
- **Riesgo:** bajo. Estas mismas librerías (python-docx, openpyxl, Pillow)
  también sirven para el lado de **lectura** que falta hoy (sección 7 de
  `ATLAS_CURRENT_ARCHITECTURE.md`) — no hace falta agregar dependencias
  nuevas para extraer texto de `.docx`/`.xlsx`, solo escribir el código que
  las use en modo lectura.

### psutil
- **Función:** info de sistema (CPU/RAM/disco). Gratis, BSD, sin riesgo.

## D — INNECESARIAS / código muerto

### `DEEPSEEK_API_KEY` (config/.env.example)
- Declarada pero **sin ningún código que la lea** en todo el repositorio.
  No es una dependencia activa — es configuración huérfana, probablemente
  de un intento anterior de diversificar proveedor. Se puede eliminar del
  `.env.example` sin ningún impacto, o formalizarse como el primer
  `AIProvider` alternativo real si la intención sigue en pie (DeepSeek es
  razonable como segundo proveedor cloud de bajo costo mientras no haya
  modelo local, pero hoy es solo una variable sin efecto).

## Resumen de exposición a Internet (para diseñar el "modo offline")

| Función | Depende de red hoy | Después de la migración propuesta |
|---|---|---|
| Chat / tool-use | Sí (Gemini) | No (modelo local) — Gemini queda de respaldo opcional |
| Decisión de memoria (cortex) | Sí (Gemini) | No (modelo local, tarea simple) |
| Embeddings / búsqueda semántica | Sí (Gemini) | No (embeddings locales) |
| Transcripción de voz | No (ya local) | Sin cambios |
| Síntesis de voz | Sí (edge-tts) | No (Piper local) |
| `web_search` | Sí, por diseño | Sin cambios (es la "fuente", no el "cerebro") |
| Visión de pantalla | Sí (Gemini multimodal) | Parcial — modelos locales pequeños con visión existen pero son más limitados; probablemente quede como el caso de uso que sí justifica caer al proveedor externo en modo híbrido |
| Generación de documentos | No (ya local) | Sin cambios |

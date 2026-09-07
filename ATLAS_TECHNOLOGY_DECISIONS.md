# ATLAS — Matriz de Decisiones Tecnológicas

> Hardware de referencia detectado en la máquina de desarrollo actual (2026-09-07):
> **Intel Core i3-1125G4** (4 núcleos / 8 hilos), **11.7 GB RAM**, GPU integrada
> Intel UHD (sin VRAM dedicada — **sin aceleración CUDA/GPU disponible**), disco
> con ~648 GB libres. Esto significa: **inferencia local será CPU-only** en esta
> máquina. Cualquier recomendación de modelo local está acotada por esto — no
> por lo que hay de más potente en el mercado, sino por lo que corre bien acá.
> Investigado con búsquedas actuales (septiembre 2026), no solo con
> conocimiento de entrenamiento — ver fuentes al pie.

## Runtime de modelos locales

| Tecnología | Alternativas | Costo | Recursos | Calidad | Local | Servidor | Comercial | Decisión |
|---|---|---|---|---|---|---|---|---|
| **Ollama** | llama.cpp (server), vLLM, LM Studio | Gratis, MIT | Medio (empaqueta llama.cpp + gestión de modelos, algo de overhead extra) | Igual que llama.cpp por debajo | Sí | Sí (mismo binario, expone API HTTP compatible OpenAI) | Sí, sin restricciones | **Elegido** para empezar |
| llama.cpp (server crudo) | Ollama | Gratis, MIT | Mínimo, control total de flags | Igual, más ajustable | Sí | Sí | Sí | Candidato para **Fase futura** si se necesita exprimir rendimiento (multi-hilo/cuantización fina) que Ollama no expone |
| vLLM / SGLang | — | Gratis | Alto (pensado para GPU/batch, no para 1 usuario en CPU) | Alta en su nicho | Sí (con GPU) | Sí | Sí | Descartado ahora — esta máquina no tiene GPU; reevaluar si se migra a servidor con GPU |

**Por qué Ollama y no llama.cpp directo:** litellm ya tiene soporte nativo
para `ollama_chat/<modelo>` (cambiar `config/settings.json` es literalmente
el mismo patrón que ya existe para Gemini). Ollama expone un API HTTP
OpenAI-compatible en `localhost:11434`, gestiona descarga/cuantización de
modelos con un comando (`ollama pull qwen3:4b`), y corre igual en Windows/
Linux/macOS — encaja con "monolito modular, no sobreingeniería". llama.cpp
da más control pero exige compilar/gestionar binarios y flags a mano; se dejó
como opción de ajuste fino, no como punto de partida. **No genera vendor
lock-in**: es un proceso local que se puede desinstalar y reemplazar sin
tocar el resto de Atlas, gracias a litellm.

## Modelo conversacional local (candidato inicial)

| Modelo | RAM aprox. (Q4_K_M) | Español/multilingüe | Function calling | Licencia comercial | Decisión |
|---|---|---|---|---|---|
| **Qwen3 4B** (o revisión más nueva de la familia Qwen3.x disponible al momento de implementar) | ~3-4 GB | Fuerte (una de las familias multilingües más consistentes según benchmarks 2026) | Soportado, calidad razonable para tareas simples | Apache 2.0 | **Candidato principal** para probar primero |
| Llama 3.2 3B | ~2-3 GB | Aceptable | Soportado | Llama Community License (permite uso comercial con condiciones si la base de usuarios es muy grande — revisar antes de escalar) | Candidato secundario |
| Gemma 4 (variante chica, ej. E2B) | ~2-3 GB | Aceptable | Limitado | Gemma license (permite uso comercial, con términos propios de Google a revisar) | Candidato secundario |
| Phi-4-mini | ~2-3 GB | Más débil en español que Qwen | Soportado | MIT | Candidato si el foco fuera predominantemente inglés |

**Decisión:** empezar con **Qwen3 (variante ~4B)** cuantizado Q4_K_M vía
Ollama, para: chat simple sin herramientas, decisión del cortex de memoria
("¿esto vale la pena guardarlo?" es una tarea de clasificación simple, no
necesita el modelo más grande), y borradores de resúmenes. **Mantener
Gemini como fallback** para: tool-use complejo de varios pasos, visión de
pantalla (multimodal), y cualquier respuesta donde la calidad del modelo
chico sea insuficiente — exactamente el "modo híbrido" que pide la visión.
No se elige un modelo "porque es popular": se elige porque (a) corre en CPU
con 4-8 GB de uso razonable en esta máquina, (b) tiene licencia comercial sin
restricciones fuertes, (c) su desempeño multilingüe/español está entre los
mejores de su clase de tamaño en las comparativas actuales.

## Embeddings locales

| Modelo | Tamaño | Multilingüe/español | Licencia | Decisión |
|---|---|---|---|---|
| **Qwen3-Embedding-0.6B** | ~0.6 GB | Fuerte, 100+ idiomas | Apache 2.0 | **Elegido** |
| nomic-embed-text | ~0.27 GB | Más limitado en español que Qwen3/BGE-M3 | Apache 2.0 | Alternativa si se prioriza tamaño mínimo sobre calidad en español |
| BGE-M3 | ~2.2 GB | Muy fuerte, soporta denso+disperso (híbrido) | MIT | Alternativa si se implementa búsqueda híbrida densa+dispersa más adelante |

**Decisión:** **Qwen3-Embedding-0.6B** vía Ollama (mismo runtime que el
modelo conversacional — un solo proceso sirviendo ambas cosas, en línea con
"no quiero instalar cinco sistemas distintos"). Reemplaza directamente
`gemini-embedding-001` en `memory/semantic.py` sin cambiar la lógica de
coseno existente, solo la fuente del vector.

## Base de conocimiento / búsqueda vectorial

| Tecnología | Alternativas | Costo | Recursos | Local | Servidor | Multiusuario | Comercial | Decisión |
|---|---|---|---|---|---|---|---|---|
| SQLite + extensión de vectores (`sqlite-vec`) | Chroma, LanceDB | Gratis | Mínimo — un solo archivo, ya es el patrón de `core/projects.py` | Sí | Limitado (SQLite no está pensado para muchas escrituras concurrentes) | No de forma nativa (habría que particionar por archivo) | Sí, sin restricción | **Elegido para AHORA** (ver justificación) |
| **PostgreSQL + pgvector** | — | Gratis (o managed de pago en el futuro, opcional) | Medio (un proceso de servidor de base de datos, vía Docker) | Sí (localmente, en un contenedor) | Sí, nativo | Sí (row-level, `user_id`/`tenant_id`) | Sí | **Elegido para el DESTINO (servidor / multiusuario / SaaS)** |
| Chroma | pgvector, LanceDB | Gratis | Bajo, embebido | Sí | Limitado hoy para multiusuario real | No nativo | Sí (Apache 2.0) | Descartado — sumaría un segundo motor de almacenamiento (además de SQLite) sin resolver mejor el problema de multiusuario que ya resuelve Postgres |
| LanceDB | pgvector, Chroma | Gratis | Bajo, buen manejo de datasets grandes en disco | Sí | Parcial (acceso concurrente limitado) | No nativo | Sí (Apache 2.0) | Descartado por el mismo motivo — no aporta sobre la ruta SQLite→Postgres ya elegida |
| Qdrant | pgvector | Gratis (self-host) / pago (cloud) | Medio-alto (proceso Rust dedicado) | Sí | Sí | Sí | Sí (Apache 2.0 el core) | Descartado — es la mejor opción para RAG a *gran escala en producción*, pero es un motor más para operar sin necesidad clara todavía; reevaluar solo si pgvector se queda corto en volumen/latencia una vez en producción real |

**Justificación de la ruta en dos pasos (no una elección única):**

El pedido explícito es "no quiero instalar cinco bases de datos diferentes"
y a la vez "quiero una sola base para usuarios, configuraciones, documentos,
conversaciones, memoria, embeddings, permisos, auditoría" con camino claro a
servidor y multiusuario. Estas dos cosas apuntan a **PostgreSQL + pgvector**
como destino: es la única opción de la tabla que de verdad puede ser esa
"única base" para todo (relacional + vectorial en las mismas transacciones,
con `user_id`/`tenant_id` como columnas normales y aislamiento por fila desde
el día uno). Pero exigir Postgres *ahora mismo*, en una app de escritorio de
un solo usuario que hoy corre con `python shell/main.py` sin más
infraestructura, viola "monolito modular, no sobreingeniería" y "menor
consumo posible" — son ~150-300 MB de RAM extra en reposo por un servidor de
base de datos que, para un solo usuario y 40 notas, no aporta nada todavía.

Por eso: **se sigue usando SQLite** (ya es el patrón elegido para
`core/projects.py`, con buen criterio) y se le agrega la extensión
`sqlite-vec` para guardar los embeddings ahí mismo, con el **esquema
diseñado desde ahora con `user_id`/`tenant_id`** aunque hoy valgan siempre
"local"/"eduardo" — igual que ya pide la sección de Multiusuario de la
visión. Cuando llegue el momento real de servidor/multiusuario (Fase 12-13
del plan de migración), migrar de SQLite a Postgres+pgvector es un `dump` +
`restore` con el mismo esquema de columnas, no un rediseño.

## OCR (documentos escaneados)

| Tecnología | Costo | Recursos | Calidad | Licencia | Decisión |
|---|---|---|---|---|---|
| **Tesseract OCR** (vía `pytesseract`) | Gratis | Bajo, CPU | Buena en texto limpio/impreso, débil en manuscrito o escaneos de baja calidad | Apache 2.0 | **Elegido para empezar** |
| EasyOCR | Gratis | Medio-alto (modelo de deep learning), más lento en CPU | Mejor que Tesseract en escaneos ruidosos/manuscritos | Apache 2.0 | **OPCIONAL — FUTURO**, si la calidad de Tesseract resulta insuficiente en la práctica |
| docTR | Gratis | Medio | Buena, orientado a documentos | Apache 2.0 | Alternativa a evaluar junto con EasyOCR si hace falta mejorar precisión |

## Extracción de texto por tipo de archivo

| Tipo | Librería | Ya está en `requirements.txt` | Licencia |
|---|---|---|---|
| PDF (texto) | `pypdf` o `pdfplumber` | No — agregar | BSD / MIT |
| PDF (escaneado) | Tesseract + `pdf2image` | No — agregar | Apache 2.0 / MIT |
| DOCX | `python-docx` (modo lectura) | **Sí, ya está** | MIT |
| XLSX/CSV | `openpyxl` (lectura) / `csv` (stdlib) | **Sí, ya está** | MIT |
| PPTX | `python-pptx` (lectura) | **Sí, ya está** | MIT |
| HTML | `beautifulsoup4` | No — agregar | MIT |
| Markdown/TXT | stdlib | — | — |
| Imágenes (metadata/OCR) | `Pillow` (ya está) + Tesseract | Parcial | MIT / Apache 2.0 |

Ninguna librería nueva necesaria para generación cambia — varias de las que
ya están instaladas para *escribir* documentos sirven también para *leerlos*,
sin sumar dependencias nuevas para docx/xlsx/pptx.

## Voz (TTS)

| Tecnología | Alternativas | Costo | Local | Calidad en español | Licencia | Decisión |
|---|---|---|---|---|---|---|
| **Piper TTS** | Coqui-TTS/XTTS, SAPI de Windows, edge-tts (actual) | Gratis | Sí | Buena, voces en español disponibles, muy liviano (CPU, tiempo real) | MIT | **Elegido para reemplazar edge-tts** |
| Coqui-TTS / XTTS | Piper | Gratis | Sí | Más natural/expresivo, pero mucho más pesado en CPU | MPL / propia (revisar términos de XTTS para uso comercial) | OPCIONAL — FUTURO, si se prioriza naturalidad de voz sobre velocidad/recursos |
| SAPI (Windows, vía `pyttsx3`) | Piper | Gratis | Sí | Notablemente peor que las neuronales | — | Descartado — calidad muy por debajo de lo que Atlas ya tiene con edge-tts |

## GUI de escritorio

| Tecnología | Alternativas | Licencia | Riesgo comercial | Decisión |
|---|---|---|---|---|
| PyQt6 (actual) | PySide6 | **GPL v3 o comercial de pago** | **Alto para un producto que se venderá** — GPL v3 obliga a licenciar el software resultante bajo GPL (incompatible con venderlo cerrado) salvo que se pague la licencia comercial de Riverbank | Migrar a **PySide6** antes de cualquier lanzamiento comercial |
| **PySide6** | PyQt6 | LGPL v3 (del propio proyecto Qt) | Bajo — LGPL permite uso comercial de la librería sin obligar a liberar el código propio de Atlas, siempre que Qt se enlace dinámicamente (el caso normal) | **Elegido como destino**, no urgente mientras Atlas sea de un solo usuario no comercializado |

Esto no es una preferencia estética: es la única entrada de esta tabla donde
seguir con la opción actual crea un **riesgo legal**, no solo técnico, si el
plan de comercializar Atlas (puntos 11/17 de la misión) sigue en pie.

## Backend / API

| Tecnología | Alternativas | Decisión |
|---|---|---|
| **FastAPI + uvicorn (actual)** | Flask, Django | Mantener — ya es la elección correcta para este perfil (async, WebSocket nativo, tipado con Pydantic, buen camino a servidor). No se propone ningún cambio aquí. |

## Contenedores

| Escenario | Decisión |
|---|---|
| Desarrollo diario | Sin Docker — `python shell/main.py` directo, como hoy. |
| Base de datos local (cuando se adopte Postgres) | Docker Compose **solo para el contenedor de Postgres**, opcional incluso ahí (SQLite cubre la etapa actual). |
| Producción / servidor futuro | `docker compose up` levantando API + Postgres + (eventual) servidor de modelo — no antes de que exista una razón real de desplegar en servidor. |

---

### Fuentes consultadas (septiembre 2026)

- Comparativas de LLMs locales chicos y cuantización GGUF para CPU (2026):
  [sitepoint.com](https://www.sitepoint.com/best-local-llm-models-2026/),
  [popularai.org](https://www.popularai.org/p/best-cpu-only-local-llm-2026),
  [localaimaster.com](https://localaimaster.com/blog/small-language-models-guide-2026)
- Ollama vs. llama.cpp (2026):
  [machinelearningmastery.com](https://machinelearningmastery.com/ollama-vs-lm-studio-vs-llama-cpp-which-local-ai-runtime-should-you-use-in-2026/)
- Embeddings multilingües locales (2026):
  [morphllm.com](https://www.morphllm.com/ollama-embedding-models),
  [d-central.tech](https://d-central.tech/local-embedding-models/)
- Bases de datos vectoriales, local-first vs. producción (2026):
  [firecrawl.dev](https://www.firecrawl.dev/blog/best-vector-databases),
  [4xxi.com](https://4xxi.com/articles/vector-database-comparison/)

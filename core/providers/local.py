"""Proveedor para un modelo corriendo localmente via Ollama, hablado
tambien a traves de litellm (litellm soporta el target `ollama_chat/<modelo>`
de forma nativa, asi que no hace falta un cliente HTTP propio).

Todavia no esta activado por defecto en ningun rol de config/settings.json
(ver ATLAS_TECHNOLOGY_DECISIONS.md para la eleccion de modelo/runtime) -
existe desde ya para que activarlo mas adelante sea cambiar una linea de
configuracion ("provider": "local" + el modelo, p. ej. "ollama_chat/qwen3:4b"),
no escribir codigo nuevo.

Un modelo local en un hardware sin GPU dedicada puede tardar bastante mas
por respuesta que una API cloud, pero no falla por limite de cuota como la
capa gratuita de Gemini - de ahi un timeout mas largo y menos reintentos
que GeminiProvider."""

from core.providers.litellm_base import LiteLLMProvider


class LocalProvider(LiteLLMProvider):
    MAX_ATTEMPTS = 2
    RETRY_DELAY_SECONDS = 1.0
    REQUEST_TIMEOUT_SECONDS = 60

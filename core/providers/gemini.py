"""Proveedor Gemini (Google AI Studio), via litellm.

Reintenta manualmente (no usa los reintentos internos de litellm) por la
inestabilidad conocida de la capa gratuita de Google - un timeout corto
(REQUEST_TIMEOUT_SECONDS) mas varios reintentos cortos responde mejor a esa
inestabilidad que esperar mucho en un solo intento."""

from core.providers.litellm_base import LiteLLMProvider


class GeminiProvider(LiteLLMProvider):
    # Mismos valores que Atlas ya usaba antes de que existiera esta clase
    # (ver ATLAS_MIGRATION_PLAN.md, Fase 2) - este proveedor envuelve el
    # comportamiento previo, no lo cambia.
    MAX_ATTEMPTS = 3
    RETRY_DELAY_SECONDS = 2.0
    REQUEST_TIMEOUT_SECONDS = 12

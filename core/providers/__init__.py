"""Punto de entrada unico de Atlas hacia cualquier modelo de IA (chat,
herramientas o embeddings). Nada fuera de este paquete debe importar
litellm ni saber que proveedor concreto (Gemini, un modelo local via
Ollama, o cualquier otro que se agregue despues) atiende cada rol - ese
mapeo vive en config/settings.json (campo "provider" de cada rol, que ya
existia en el archivo pero no se leia hasta ahora) y se resuelve aca.

Agregar un proveedor nuevo (otro modelo cloud, un servidor propio, etc.)
significa: crear una clase que implemente AIProvider en un modulo nuevo
bajo core/providers/, sumarla a _PROVIDER_CLASSES, y listo - ningun otro
archivo de Atlas cambia. core/agent.py, memory/cortex.py, memory/semantic.py
y skills/vision.py siguen llamando a las mismas cuatro funciones de siempre
(stream_reply, stream_agent_turn, complete, embed) con la misma firma que
ya usaban antes de que existiera este paquete."""

from collections.abc import AsyncIterator

from core.config import load_settings, model_for_role
from core.providers.base import AIProvider
from core.providers.gemini import GeminiProvider
from core.providers.local import LocalProvider

_PROVIDER_CLASSES: dict[str, type[AIProvider]] = {
    "google": GeminiProvider,
    "local": LocalProvider,
}

# Instancias unicas por proveedor (no por rol) - conversational y
# memory_cortex hoy comparten "google" en settings.json, no hace falta
# crear un GeminiProvider por cada uno.
_provider_instances: dict[str, AIProvider] = {}


def _provider_for_role(role: str) -> AIProvider:
    settings = load_settings()
    role_cfg = settings["roles"].get(role)
    if role_cfg is None:
        raise ValueError(f"No hay modelo configurado para el rol '{role}'")

    provider_name = role_cfg.get("provider", "google")
    if provider_name not in _provider_instances:
        provider_cls = _PROVIDER_CLASSES.get(provider_name)
        if provider_cls is None:
            raise ValueError(f"Proveedor de IA desconocido: '{provider_name}'")
        _provider_instances[provider_name] = provider_cls()
    return _provider_instances[provider_name]


async def stream_reply(role: str, messages: list[dict]) -> AsyncIterator[str]:
    provider = _provider_for_role(role)
    model = model_for_role(role)
    async for chunk in provider.stream_reply(model, messages):
        yield chunk


async def stream_agent_turn(
    role: str, messages: list[dict], tools: list[dict]
) -> AsyncIterator[dict]:
    provider = _provider_for_role(role)
    model = model_for_role(role)
    async for event in provider.stream_agent_turn(model, messages, tools):
        yield event


async def complete(
    role: str, messages: list[dict], max_attempts: int | None = None
) -> str:
    provider = _provider_for_role(role)
    model = model_for_role(role)
    return await provider.complete(model, messages, max_attempts)


async def embed(
    role: str, texts: list[str], max_attempts: int | None = None
) -> list[list[float]]:
    provider = _provider_for_role(role)
    model = model_for_role(role)
    return await provider.embed(model, texts, max_attempts)

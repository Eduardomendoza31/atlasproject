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
ya usaban antes de que existiera este paquete.

Fase 7 del plan de migracion sumo a este mismo paquete el modo hibrido
(`try_local_first`): un intento de responder con un modelo local ANTES del
proveedor normal del rol, solo cuando el turno no termina pidiendo ninguna
herramienta - la calidad de tool-use de un modelo chico no esta probada lo
suficiente como para confiarle eso (ver ATLAS_MIGRATION_PLAN.md, Fase 7, y
el hallazgo de la Fase 4 sobre embeddings locales, misma clase de riesgo)."""

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


def _local_first_model(role: str) -> str | None:
    """El modelo local a intentar primero para este rol en modo hibrido
    (Fase 7), o None si no esta activado. Vive en `roles.<rol>.local_first`
    de config/settings.json, separado del campo "provider" normal del rol
    (que sigue siendo el proveedor de fallback/definitivo, no cambia)."""
    settings = load_settings()
    local_first = settings["roles"].get(role, {}).get("local_first")
    if local_first and local_first.get("enabled"):
        return local_first["model"]
    return None


async def try_local_first(
    role: str, messages: list[dict], tools: list[dict]
) -> str | None:
    """Intenta resolver este turno con el modelo local configurado como
    `local_first` de este rol, antes de usar el proveedor normal. Devuelve
    el texto de la respuesta si el modelo local respondio directamente, sin
    pedir ninguna herramienta - o None si hay que resolver el turno con el
    proveedor normal, porque el modo hibrido no esta activado para este
    rol, el modelo local pidio usar una herramienta (su tool-use no esta
    probado lo suficiente para confiarle eso, asi que se descarta el
    intento entero en vez de arriesgar un argumento mal formado), o fallo
    por cualquier motivo (incluido que Ollama no este corriendo).

    Se descarta el intento entero (no se emite nada) recien cuando ya se
    sabe que hace falta una herramienta o que hubo un error - no hay
    streaming parcial hacia el usuario de un intento local que despues se
    puede llegar a descartar."""
    model = _local_first_model(role)
    if model is None:
        return None

    provider = _provider_instances.setdefault("local", LocalProvider())
    local_messages = [dict(m) for m in messages]  # no mutar la lista real
    try:
        text = ""
        for_tool_use = False
        async for event in provider.stream_agent_turn(model, local_messages, tools):
            if event["type"] == "text":
                text += event["text"]
            else:
                for_tool_use = True
                break
        if for_tool_use or not text.strip():
            return None
        return text
    except Exception as exc:
        print(f"[Híbrido] el modelo local no pudo responder, sigo con el proveedor normal: {exc}", flush=True)
        return None

"""Contrato que cualquier proveedor de IA debe cumplir para que el resto de
Atlas (core/agent.py, memory/cortex.py, memory/semantic.py, skills/vision.py)
pueda usarlo sin saber si detras hay Gemini, un modelo local via Ollama, o
cualquier otro proveedor que se agregue despues.

Ninguno de estos metodos sabe de "roles" (conversational/memory_cortex/
embeddings) - eso lo resuelve core/providers/__init__.py antes de llegar
aca. Un AIProvider solo sabe hablar con UN modelo concreto (el string
`model` que recibe en cada llamada), sea cual sea el rol que lo pidio.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class AIProvider(ABC):
    @abstractmethod
    def stream_reply(self, model: str, messages: list[dict]) -> AsyncIterator[str]:
        """Respuesta en texto, en trozos, a medida que el modelo la genera."""

    @abstractmethod
    def stream_agent_turn(
        self, model: str, messages: list[dict], tools: list[dict]
    ) -> AsyncIterator[dict]:
        """Como stream_reply, pero el modelo puede pedir usar herramientas.
        Emite eventos {"type": "text", "text": str} y
        {"type": "tool_call", "id", "name", "arguments"} - ver
        core/providers/litellm_base.py para como se arman."""

    @abstractmethod
    async def complete(
        self, model: str, messages: list[dict], max_attempts: int | None = None
    ) -> str:
        """Version no-streaming, para llamadas cortas de una sola respuesta."""

    @abstractmethod
    async def embed(
        self, model: str, texts: list[str], max_attempts: int | None = None
    ) -> list[list[float]]:
        """Convierte cada texto en un vector numerico, en el mismo orden
        que la lista de entrada."""

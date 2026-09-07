"""Implementacion compartida de AIProvider para cualquier modelo que se
hable via litellm (Gemini, un modelo local servido por Ollama, o cualquier
otro backend que litellm soporte) - la logica de reintentos/timeouts/
streaming es identica entre ellos, lo unico que cambia de un proveedor a
otro son las constantes de la clase (ver core/providers/gemini.py y
core/providers/local.py).

Este modulo es exactamente el codigo que antes vivia suelto en
core/providers.py (antes de la Fase 2 del plan de migracion), movido a
metodos de instancia sin cambiar ninguna linea de comportamiento."""

import asyncio
import json
from collections.abc import AsyncIterator

import litellm

from core.providers.base import AIProvider


class LiteLLMProvider(AIProvider):
    MAX_ATTEMPTS = 3
    RETRY_DELAY_SECONDS = 2.0
    REQUEST_TIMEOUT_SECONDS = 12
    NUM_INTERNAL_RETRIES = 0  # los reintentos los manejamos nosotros, no litellm

    async def stream_reply(self, model: str, messages: list[dict]) -> AsyncIterator[str]:
        """Reintenta ante fallos transitorios del proveedor antes de dejar
        que el error suba al llamador."""
        last_error: Exception | None = None

        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            yielded_any = False
            try:
                response = await asyncio.wait_for(
                    litellm.acompletion(
                        model=model,
                        messages=messages,
                        stream=True,
                        timeout=self.REQUEST_TIMEOUT_SECONDS,
                        num_retries=self.NUM_INTERNAL_RETRIES,
                    ),
                    timeout=self.REQUEST_TIMEOUT_SECONDS,
                )
                stream = response.__aiter__()
                while True:
                    chunk = await asyncio.wait_for(
                        stream.__anext__(), timeout=self.REQUEST_TIMEOUT_SECONDS
                    )
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yielded_any = True
                        yield delta
            except StopAsyncIteration:
                return
            except Exception as exc:
                last_error = exc
                # Si ya empezamos a mandar texto al cliente, reintentar
                # duplicaria el inicio de la respuesta - mejor propagar el error.
                if yielded_any or attempt == self.MAX_ATTEMPTS:
                    raise
                await asyncio.sleep(self.RETRY_DELAY_SECONDS * attempt)

        raise last_error

    async def stream_agent_turn(
        self, model: str, messages: list[dict], tools: list[dict]
    ) -> AsyncIterator[dict]:
        """Gemini (y otros proveedores compatibles) mandan los fragmentos
        de cada llamada a herramienta repartidos en varios chunks
        (delta.tool_calls) - hay que ir acumulando id/nombre/argumentos (un
        JSON parcial) por indice y recien armar+parsear cada llamada
        completa cuando el stream termina, nunca a mitad de camino."""
        last_error: Exception | None = None

        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            yielded_any = False
            tool_calls_acc: dict[int, dict] = {}
            try:
                response = await asyncio.wait_for(
                    litellm.acompletion(
                        model=model,
                        messages=messages,
                        tools=tools,
                        stream=True,
                        timeout=self.REQUEST_TIMEOUT_SECONDS,
                        num_retries=self.NUM_INTERNAL_RETRIES,
                    ),
                    timeout=self.REQUEST_TIMEOUT_SECONDS,
                )
                stream = response.__aiter__()
                while True:
                    chunk = await asyncio.wait_for(
                        stream.__anext__(), timeout=self.REQUEST_TIMEOUT_SECONDS
                    )
                    delta = chunk.choices[0].delta
                    if delta.content:
                        yielded_any = True
                        yield {"type": "text", "text": delta.content}
                    if getattr(delta, "tool_calls", None):
                        yielded_any = True
                        for tc in delta.tool_calls:
                            entry = tool_calls_acc.setdefault(
                                tc.index, {"id": None, "name": None, "arguments_buffer": ""}
                            )
                            if tc.id:
                                entry["id"] = tc.id
                            if tc.function and tc.function.name:
                                entry["name"] = tc.function.name
                            if tc.function and tc.function.arguments:
                                entry["arguments_buffer"] += tc.function.arguments
            except StopAsyncIteration:
                for index, entry in tool_calls_acc.items():
                    try:
                        args = json.loads(entry["arguments_buffer"] or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    yield {
                        "type": "tool_call",
                        "id": entry["id"] or f"call_{index}",
                        "name": entry["name"],
                        "arguments": args,
                    }
                return
            except Exception as exc:
                last_error = exc
                if yielded_any or attempt == self.MAX_ATTEMPTS:
                    raise
                await asyncio.sleep(self.RETRY_DELAY_SECONDS * attempt)

        raise last_error

    async def complete(
        self, model: str, messages: list[dict], max_attempts: int | None = None
    ) -> str:
        """Para llamadas cortas de una sola respuesta (p. ej. el cortex de
        memoria), donde no hace falta ir mostrando texto palabra por
        palabra. Reintenta igual que stream_reply.

        Las llamadas que corren en segundo plano (sin que el usuario este
        esperando en pantalla) pueden pasar un max_attempts mas alto."""
        attempts = max_attempts if max_attempts is not None else self.MAX_ATTEMPTS
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = await asyncio.wait_for(
                    litellm.acompletion(
                        model=model,
                        messages=messages,
                        stream=False,
                        timeout=self.REQUEST_TIMEOUT_SECONDS,
                        num_retries=self.NUM_INTERNAL_RETRIES,
                    ),
                    timeout=self.REQUEST_TIMEOUT_SECONDS,
                )
                return response.choices[0].message.content or ""
            except Exception as exc:
                last_error = exc
                if attempt < attempts:
                    await asyncio.sleep(self.RETRY_DELAY_SECONDS * attempt)

        raise last_error

    async def embed(
        self, model: str, texts: list[str], max_attempts: int | None = None
    ) -> list[list[float]]:
        """Se usa para busqueda semantica en la memoria de largo plazo."""
        attempts = max_attempts if max_attempts is not None else self.MAX_ATTEMPTS
        last_error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = await asyncio.wait_for(
                    litellm.aembedding(
                        model=model,
                        input=texts,
                        timeout=self.REQUEST_TIMEOUT_SECONDS,
                        num_retries=self.NUM_INTERNAL_RETRIES,
                    ),
                    timeout=self.REQUEST_TIMEOUT_SECONDS,
                )
                return [item["embedding"] for item in response.data]
            except Exception as exc:
                last_error = exc
                if attempt < attempts:
                    await asyncio.sleep(self.RETRY_DELAY_SECONDS * attempt)

        raise last_error

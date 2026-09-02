import asyncio
from collections.abc import AsyncIterator

import litellm

from core.config import model_for_role

MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 2.0
REQUEST_TIMEOUT_SECONDS = 12
NUM_INTERNAL_RETRIES = 0  # los reintentos los manejamos nosotros, no litellm


async def stream_reply(role: str, messages: list[dict]) -> AsyncIterator[str]:
    """Envia la conversacion al modelo asignado al rol dado y devuelve la
    respuesta en trozos, a medida que el modelo la genera.

    Reintenta ante fallos transitorios del proveedor (comunes en la capa
    gratuita de Google) antes de dejar que el error suba al llamador."""
    model = model_for_role(role)
    last_error: Exception | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        yielded_any = False
        try:
            response = await asyncio.wait_for(
                litellm.acompletion(
                    model=model,
                    messages=messages,
                    stream=True,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                    num_retries=NUM_INTERNAL_RETRIES,
                ),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            stream = response.__aiter__()
            while True:
                chunk = await asyncio.wait_for(
                    stream.__anext__(), timeout=REQUEST_TIMEOUT_SECONDS
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
            if yielded_any or attempt == MAX_ATTEMPTS:
                raise
            await asyncio.sleep(RETRY_DELAY_SECONDS * attempt)

    raise last_error


async def complete(
    role: str, messages: list[dict], max_attempts: int = MAX_ATTEMPTS
) -> str:
    """Version no-streaming: para llamadas cortas de una sola respuesta
    (p. ej. el cortex de memoria), donde no hace falta ir mostrando texto
    palabra por palabra. Reintenta igual que stream_reply.

    Las llamadas que corren en segundo plano (sin que el usuario este
    esperando en pantalla) pueden pasar un max_attempts mas alto: no hay
    costo de UX por insistir mas ante la inestabilidad de la capa
    gratuita de Google."""
    model = model_for_role(role)
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            response = await asyncio.wait_for(
                litellm.acompletion(
                    model=model,
                    messages=messages,
                    stream=False,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                    num_retries=NUM_INTERNAL_RETRIES,
                ),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            return response.choices[0].message.content or ""
        except Exception as exc:
            last_error = exc
            if attempt < max_attempts:
                await asyncio.sleep(RETRY_DELAY_SECONDS * attempt)

    raise last_error


async def embed(
    role: str, texts: list[str], max_attempts: int = MAX_ATTEMPTS
) -> list[list[float]]:
    """Convierte cada texto en un vector numerico (embedding), en el mismo
    orden que la lista de entrada. Se usa para busqueda semantica en la
    memoria de largo plazo."""
    model = model_for_role(role)
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            response = await asyncio.wait_for(
                litellm.aembedding(
                    model=model,
                    input=texts,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                    num_retries=NUM_INTERNAL_RETRIES,
                ),
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            return [item["embedding"] for item in response.data]
        except Exception as exc:
            last_error = exc
            if attempt < max_attempts:
                await asyncio.sleep(RETRY_DELAY_SECONDS * attempt)

    raise last_error

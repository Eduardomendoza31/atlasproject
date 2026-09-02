import asyncio
from collections.abc import AsyncIterator

import litellm

from core.config import model_for_role

MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 1.5
REQUEST_TIMEOUT_SECONDS = 20
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
            response = await litellm.acompletion(
                model=model,
                messages=messages,
                stream=True,
                timeout=REQUEST_TIMEOUT_SECONDS,
                num_retries=NUM_INTERNAL_RETRIES,
            )
            async for chunk in response:
                delta = chunk.choices[0].delta.content
                if delta:
                    yielded_any = True
                    yield delta
            return
        except Exception as exc:
            last_error = exc
            # Si ya empezamos a mandar texto al cliente, reintentar
            # duplicaria el inicio de la respuesta - mejor propagar el error.
            if yielded_any or attempt == MAX_ATTEMPTS:
                raise
            await asyncio.sleep(RETRY_DELAY_SECONDS * attempt)

    raise last_error

import asyncio
import base64

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from core.config import USER_NAME
from core.providers import stream_reply
from core.voice import synthesize, transcribe
from memory.cortex import maybe_save, relevant_context

app = FastAPI(title="Atlas Core")

background_tasks: set[asyncio.Task] = set()


def _save_to_memory_in_background(user_text: str, reply: str) -> None:
    task = asyncio.create_task(maybe_save(user_text, reply))
    background_tasks.add(task)

    def _on_done(t: asyncio.Task) -> None:
        background_tasks.discard(t)
        if t.cancelled() or t.exception():
            return
        title = t.result()
        if title:
            print(f"[Cortex] Nota guardada: {title}", flush=True)

    task.add_done_callback(_on_done)


SYSTEM_PROMPT = (
    "Eres Atlas, un asistente personal que corre en el ordenador de "
    f"{USER_NAME}. Responde en español, de forma breve y natural, como en "
    "una conversación hablada.\n\n"
    "Regla estricta sobre datos personales: NUNCA inventes ni supongas "
    "datos sobre el usuario (edad, empresa, nombres, cifras, fechas, "
    "etc.). Solo puedes afirmar un dato personal si aparece explicito en "
    "un bloque 'Memoria relevante de conversaciones pasadas' que se te "
    "haya dado en este mismo turno, o si el usuario lo acaba de decir en "
    "la conversacion actual. Si no tienes ese dato, dilo claramente "
    "('no lo tengo guardado, ¿me lo confirmas?') en vez de adivinar."
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.websocket("/ws/chat")
async def chat(websocket: WebSocket):
    await websocket.accept()
    history: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    try:
        while True:
            incoming = await websocket.receive_json()

            if incoming["type"] == "audio":
                audio_bytes = base64.b64decode(incoming["data"])
                try:
                    user_text = await transcribe(audio_bytes, suffix=".wav")
                except Exception as exc:
                    await websocket.send_json(
                        {"type": "error", "text": f"No pude transcribir el audio: {exc}"}
                    )
                    continue
                if not user_text:
                    continue
                await websocket.send_json({"type": "transcript", "text": user_text})
            else:
                user_text = incoming["text"]

            history.append({"role": "user", "content": user_text})

            context = await relevant_context(user_text)
            print(f"[Cortex] contexto para {user_text!r}: {context!r}", flush=True)
            messages = history.copy()
            if context:
                messages.insert(-1, {"role": "system", "content": context})

            reply = ""
            try:
                async for chunk in stream_reply("conversational", messages):
                    reply += chunk
                    await websocket.send_json({"type": "chunk", "text": chunk})
            except Exception as exc:
                await websocket.send_json(
                    {
                        "type": "error",
                        "text": f"Fallo al hablar con el modelo: {exc}",
                    }
                )
                continue

            history.append({"role": "assistant", "content": reply})
            await websocket.send_json({"type": "done"})
            _save_to_memory_in_background(user_text, reply)

            try:
                audio_reply = await synthesize(reply)
                await websocket.send_json(
                    {
                        "type": "audio_reply",
                        "data": base64.b64encode(audio_reply).decode("ascii"),
                    }
                )
            except Exception as exc:
                print(f"[Voz] Fallo al generar audio: {exc}", flush=True)
    except WebSocketDisconnect:
        pass

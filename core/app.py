import asyncio
import base64

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from core.agent import run_agent_turn
from core.config import USER_NAME
from core.tools import RUN_COMMAND_UI_OUTPUT_CAP, Tool
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
    "('no lo tengo guardado, ¿me lo confirmas?') en vez de adivinar.\n\n"
    "Sobre las herramientas: tienes acceso a herramientas para leer "
    "archivos, listar carpetas, escribir archivos, ejecutar comandos de "
    "PowerShell en el ordenador del usuario, y buscar en internet. Usa "
    "la busqueda en internet cuando te pregunten algo actual o que no "
    "sepas con certeza, en vez de inventar una respuesta. Las herramientas mas "
    "delicadas (escribir archivos, ejecutar comandos) requieren que el "
    "usuario confirme antes de correr - puede que tarde en responder, o "
    "que decida denegar el permiso. Si el usuario deniega una "
    "herramienta, no insistas ni la repitas de inmediato: continua la "
    "conversacion con naturalidad, explica brevemente que no pudiste "
    "hacer eso y, si tiene sentido, ofrece una alternativa. Nunca "
    "asumas que una herramienta se ejecuto si el resultado que "
    "recibiste indica que fue denegada."
)


@app.get("/health")
async def health():
    return {"status": "ok"}


async def _run_turn(
    websocket: WebSocket,
    history: list[dict],
    user_text: str,
    pending_confirmations: dict[str, asyncio.Future],
) -> None:
    """Corre un turno completo (posiblemente con varias idas y vueltas de
    herramientas) como una tarea de fondo, para que el loop principal del
    websocket pueda seguir escuchando mensajes (una cancelacion, o una
    respuesta de confirmacion) mientras el turno esta en curso."""
    context = await relevant_context(user_text)
    print(f"[Cortex] contexto para {user_text!r}: {context!r}", flush=True)
    messages = history.copy()
    if context:
        messages.insert(-1, {"role": "system", "content": context})

    async def confirm(tool_call_id: str, tool: Tool, arguments: dict) -> bool:
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        pending_confirmations[tool_call_id] = future
        try:
            return await future
        finally:
            pending_confirmations.pop(tool_call_id, None)

    reply_text = ""
    try:
        async for event in run_agent_turn("conversational", messages, confirm):
            etype = event["type"]
            if etype == "text":
                await websocket.send_json({"type": "chunk", "text": event["text"]})
            elif etype == "tool_call":
                await websocket.send_json({
                    "type": "tool_call",
                    "id": event["id"],
                    "name": event["name"],
                    "arguments": event["arguments"],
                })
            elif etype == "tool_confirm_needed":
                await websocket.send_json({
                    "type": "tool_confirm_request",
                    "id": event["id"],
                    "name": event["name"],
                    "tier": event["tier"],
                    "description": event["description"],
                })
            elif etype == "tool_result":
                result = event["result"]
                if event["name"] == "run_command" and len(result) > RUN_COMMAND_UI_OUTPUT_CAP:
                    result = result[:RUN_COMMAND_UI_OUTPUT_CAP] + "\n[salida truncada en pantalla]"
                await websocket.send_json({
                    "type": "tool_result",
                    "id": event["id"],
                    "name": event["name"],
                    "result": result,
                    "denied": event["denied"],
                })
            elif etype == "turn_done":
                reply_text = event["final_text"]
    except asyncio.CancelledError:
        # No se adopta el `messages` a medio terminar: puede tener una
        # llamada a herramienta sin su resultado, lo cual rompe la
        # siguiente llamada a la API. Se deja `history` como estaba
        # (con el mensaje del usuario ya puesto) y el proximo turno
        # arranca limpio.
        await websocket.send_json({"type": "stopped"})
        return
    except Exception as exc:
        await websocket.send_json(
            {"type": "error", "text": f"Fallo al hablar con el modelo: {exc}"}
        )
        return

    history[:] = messages
    await websocket.send_json({"type": "done"})
    _save_to_memory_in_background(user_text, reply_text)

    try:
        audio_reply = await synthesize(reply_text)
        await websocket.send_json(
            {
                "type": "audio_reply",
                "data": base64.b64encode(audio_reply).decode("ascii"),
            }
        )
    except Exception as exc:
        print(f"[Voz] Fallo al generar audio: {exc}", flush=True)


@app.websocket("/ws/chat")
async def chat(websocket: WebSocket):
    await websocket.accept()
    history: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    current_turn_task: asyncio.Task | None = None
    pending_confirmations: dict[str, asyncio.Future] = {}

    try:
        while True:
            incoming = await websocket.receive_json()
            msg_type = incoming.get("type")

            if msg_type == "stop":
                if current_turn_task and not current_turn_task.done():
                    current_turn_task.cancel()
                continue

            if msg_type == "tool_confirm_response":
                future = pending_confirmations.get(incoming.get("id"))
                if future and not future.done():
                    future.set_result(bool(incoming.get("approved")))
                continue

            if msg_type == "audio":
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

            if current_turn_task and not current_turn_task.done():
                await websocket.send_json(
                    {"type": "error", "text": "Ya hay un turno en curso."}
                )
                continue

            history.append({"role": "user", "content": user_text})
            current_turn_task = asyncio.create_task(
                _run_turn(websocket, history, user_text, pending_confirmations)
            )
    except WebSocketDisconnect:
        if current_turn_task and not current_turn_task.done():
            current_turn_task.cancel()

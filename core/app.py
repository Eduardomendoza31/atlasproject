from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from core.config import USER_NAME
from core.providers import stream_reply

app = FastAPI(title="Atlas Core")

SYSTEM_PROMPT = (
    "Eres Atlas, un asistente personal que corre en el ordenador de "
    f"{USER_NAME}. Responde en español, de forma breve y natural, como en "
    "una conversación hablada."
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
            user_text = await websocket.receive_text()
            history.append({"role": "user", "content": user_text})

            reply = ""
            try:
                async for chunk in stream_reply("conversational", history):
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
    except WebSocketDisconnect:
        pass

import json
import logging
import os
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .session import SessionManager

# Set up comprehensive session logging to file
LOG_DIR = "/tmp/yanki_logs"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)
LOG_FILEPATH = os.path.join(LOG_DIR, f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

# Setup both console and file handlers
file_handler = logging.FileHandler(LOG_FILEPATH)
file_handler.setLevel(logging.DEBUG)  # Comprehensive logging for session
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

formatter = logging.Formatter("%(asctime)s [%(name)s] [%(levelname)s] %(message)s")
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

logger = logging.getLogger(__name__)
# Attach handlers to root logger so all modules inherit them
logging.root.setLevel(logging.DEBUG)
for h in logging.root.handlers[:]:
    logging.root.removeHandler(h)
logging.root.addHandler(file_handler)
logging.root.addHandler(console_handler)

# Silence the websockets debug spam
logging.getLogger("websockets.client").setLevel(logging.WARNING)
logging.getLogger("websockets.server").setLevel(logging.WARNING)

app = FastAPI(title="Echo - Voice Web Navigator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/logs")
async def download_logs():
    return FileResponse(LOG_FILEPATH, media_type="text/plain", filename="session_logs.txt")



@app.get("/health")
async def health():
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("Client connected")

    session = SessionManager(websocket)
    try:
        await session.start()

        while True:
            message = await websocket.receive()

            if message.get("type") == "websocket.disconnect":
                break

            if "bytes" in message:
                # Raw binary PCM audio from client microphone
                await session.handle_client_audio(message["bytes"])

            elif "text" in message:
                # JSON control message
                data = json.loads(message["text"])
                await session.handle_client_message(data)

    except WebSocketDisconnect:
        logger.info("Client disconnected")
    except Exception:
        logger.exception("WebSocket error")
    finally:
        await session.shutdown()

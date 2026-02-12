from __future__ import annotations

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse

from .config import settings
from .twilio.twiml import build_connect_stream_twiml
from .ws.twilio_handler import TwilioHandler

app = FastAPI()


@app.get("/health")
async def health():
    return {"status": "ok", "service": "voice_gateway"}


@app.post("/twilio/inbound")
@app.get("/twilio/inbound")
async def inbound(request: Request):
    ws_url = settings.public_voice_url.replace("http", "ws", 1) + "/twilio/stream"
    twiml = build_connect_stream_twiml(ws_url)
    return PlainTextResponse(content=twiml, media_type="text/xml")


@app.websocket("/twilio/stream")
async def twilio_stream(websocket: WebSocket):
    handler = TwilioHandler(websocket)
    try:
        await handler.start()
        await handler.wait_until_done()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass

from __future__ import annotations

from fastapi import FastAPI

from .routes.tools import router as tools_router

app = FastAPI()


@app.get("/health")
async def health():
    return {"status": "ok", "service": "backend"}


app.include_router(tools_router)

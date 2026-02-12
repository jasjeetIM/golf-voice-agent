from __future__ import annotations

"""FastAPI app entrypoint for the backend tools service."""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from .db import close_pool, init_pool
from .routes.tools import router as tools_router


@asynccontextmanager
async def app_lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initializes and tears down shared infrastructure for the app lifecycle."""
    await init_pool()
    try:
        yield
    finally:
        await close_pool()


def create_app() -> FastAPI:
    """Builds and configures the backend FastAPI application."""
    app = FastAPI(lifespan=app_lifespan)
    app.include_router(tools_router)
    return app


app = create_app()


@app.get("/health")
async def health():
    """Lightweight liveness endpoint for orchestration and local checks."""
    return {"status": "ok", "service": "backend"}

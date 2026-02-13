"""FastAPI app entrypoint for the backend tools service."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from .config import settings
from .db import close_pool, init_pool
from .routes.tools import router as tools_router

_LOGGER = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Configures backend logger level from settings."""
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        )
    else:
        root_logger.setLevel(level)
    _LOGGER.setLevel(level)
    logging.getLogger("backend").setLevel(level)
    _LOGGER.debug("Backend logging configured.", extra={"log_level": settings.LOG_LEVEL})


@asynccontextmanager
async def app_lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initializes and tears down shared infrastructure for the app lifecycle."""
    _LOGGER.debug("Backend lifespan startup: initializing DB pool.")
    await init_pool()
    try:
        yield
    finally:
        _LOGGER.debug("Backend lifespan shutdown: closing DB pool.")
        await close_pool()


def create_app() -> FastAPI:
    """Builds and configures the backend FastAPI application."""
    app = FastAPI(lifespan=app_lifespan)
    app.include_router(tools_router)
    return app


_configure_logging()
app = create_app()


@app.get("/health")
async def health() -> dict[str, str]:
    """Returns a minimal liveness response for orchestration checks."""
    return {"status": "ok", "service": "backend"}

"""FastAPI entrypoint for Twilio webhook and media-stream handling.

This module performs four primary responsibilities:
1. Validate Twilio webhook and websocket signatures.
2. Return TwiML for inbound calls so Twilio opens a media stream.
3. Host the websocket endpoint that bridges Twilio and the realtime agent.
4. Manage process-lifecycle resources such as the observability DB pool.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from collections.abc import Iterable
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import PlainTextResponse

from .config import settings
from .observability.db import close_pool, init_pool
from .twilio.twiml import build_connect_stream_twiml
from .ws.twilio_handler import TwilioHandler

_LOGGER = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Configures runtime log level for gateway lifecycle tracing."""
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    observability_level = getattr(
        logging,
        settings.OBSERVABILITY_LOG_LEVEL.upper(),
        logging.INFO,
    )
    websockets_level = getattr(
        logging,
        settings.WEBSOCKETS_LOG_LEVEL.upper(),
        logging.INFO,
    )
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        )
    else:
        root_logger.setLevel(level)

    _LOGGER.setLevel(level)
    logging.getLogger("voice_gateway").setLevel(level)
    logging.getLogger("voice_gateway.app.observability").setLevel(observability_level)
    logging.getLogger("websockets").setLevel(websockets_level)
    logging.getLogger("websockets.client").setLevel(websockets_level)
    _LOGGER.debug(
        "Logging configured for voice gateway.",
        extra={
            "log_level": settings.LOG_LEVEL,
            "observability_log_level": settings.OBSERVABILITY_LOG_LEVEL,
            "websockets_log_level": settings.WEBSOCKETS_LOG_LEVEL,
            "validate_twilio_signatures": settings.VALIDATE_TWILIO_SIGNATURES,
        },
    )


def _compute_twilio_signature(
    auth_token: str,
    url: str,
    params: Iterable[tuple[str, str]],
) -> str:
    """Computes the Twilio HMAC-SHA1 signature for a request.

    Args:
        auth_token: Twilio account auth token used as HMAC key.
        url: URL Twilio used when it generated the signature.
        params: Request parameters that participate in signing.

    Returns:
        Base64-encoded HMAC-SHA1 signature.
    """
    # Twilio requires parameters sorted by key before concatenation.
    sorted_pairs = sorted(((key, value) for key, value in params), key=lambda pair: pair[0])
    _LOGGER.debug(
        "Computing Twilio signature for candidate URL.",
        extra={"url": url, "param_count": len(sorted_pairs)},
    )
    payload = url + "".join(f"{key}{value}" for key, value in sorted_pairs)
    digest = hmac.new(auth_token.encode("utf-8"), payload.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


def _build_candidate_urls(
    observed_url: str,
    configured_base_url: str,
    path: str,
    query: str,
) -> list[str]:
    """Builds URL variants for signature checks across proxy topologies.

    Args:
        observed_url: URL as seen by FastAPI in the current environment.
        configured_base_url: Public externally-reachable base URL.
        path: Request path.
        query: Raw query string.

    Returns:
        Ordered list of candidate URLs to verify.
    """
    # Request URL seen by FastAPI may differ from Twilio's signed URL when
    # reverse proxies rewrite host/scheme. Validate against both forms.
    candidates = [observed_url]
    configured_url = f"{configured_base_url.rstrip('/')}{path}"
    if query:
        configured_url = f"{configured_url}?{query}"
    if configured_url not in candidates:
        candidates.append(configured_url)
    _LOGGER.debug(
        "Built Twilio signature candidate URLs.",
        extra={"observed_url": observed_url, "configured_url": configured_url, "candidate_count": len(candidates)},
    )
    return candidates


def _is_twilio_signature_valid(
    signature: str,
    auth_token: str,
    candidate_urls: Iterable[str],
    params: Iterable[tuple[str, str]],
) -> bool:
    """Checks whether a provided signature matches any candidate URL.

    Args:
        signature: Signature received from `X-Twilio-Signature`.
        auth_token: Twilio auth token used for verification.
        candidate_urls: URL candidates to test.
        params: Parameters used during signature computation.

    Returns:
        True when a candidate URL produces the same signature.
    """
    if not signature:
        return False
    # Convert once because each candidate URL reuses the same params.
    candidate_url_list = list(candidate_urls)
    params_list = list(params)
    _LOGGER.debug(
        "Validating Twilio signature against candidate URLs.",
        extra={
            "signature_present": bool(signature),
            "candidate_count": len(candidate_url_list),
            "param_count": len(params_list),
        },
    )
    for url in candidate_url_list:
        expected = _compute_twilio_signature(auth_token, url, params_list)
        if hmac.compare_digest(signature, expected):
            _LOGGER.debug("Twilio signature matched candidate URL.", extra={"url": url})
            return True
    _LOGGER.debug("Twilio signature did not match any candidate URL.")
    return False


async def _validate_twilio_http_request(request: Request) -> bool:
    """Validates `X-Twilio-Signature` for inbound HTTP webhooks.

    Args:
        request: FastAPI request object for Twilio webhook.

    Returns:
        True when signature verification succeeds or validation is disabled.
    """
    if not settings.VALIDATE_TWILIO_SIGNATURES:
        _LOGGER.debug("Twilio HTTP signature validation disabled by config.")
        return True
    if not settings.TWILIO_AUTH_TOKEN:
        _LOGGER.error("Twilio signature validation is enabled but TWILIO_AUTH_TOKEN is empty.")
        return False

    _LOGGER.debug(
        "Validating Twilio HTTP webhook signature.",
        extra={"method": request.method, "path": request.url.path, "query": request.url.query},
    )
    signature = request.headers.get("X-Twilio-Signature", "")
    query = request.url.query
    params: list[tuple[str, str]] = list(request.query_params.multi_items())
    if request.method.upper() == "POST":
        # For form posts, Twilio signs form fields (not query params).
        form = await request.form()
        params = [(key, str(value)) for key, value in form.multi_items()]
        _LOGGER.debug(
            "Parsed Twilio HTTP form parameters for signature validation.",
            extra={"form_keys": sorted(form.keys())},
        )

    candidate_urls = _build_candidate_urls(
        observed_url=str(request.url),
        configured_base_url=settings.public_voice_url,
        path=request.url.path,
        query=query,
    )
    _LOGGER.debug(
        "HTTP signature validation inputs prepared.",
        extra={"candidate_urls": candidate_urls, "signature_present": bool(signature)},
    )
    return _is_twilio_signature_valid(signature, settings.TWILIO_AUTH_TOKEN, candidate_urls, params)


def _validate_twilio_ws_request(websocket: WebSocket) -> bool:
    """Validates `X-Twilio-Signature` for websocket upgrade requests.

    Args:
        websocket: FastAPI websocket connection object.

    Returns:
        True when signature verification succeeds or validation is disabled.
    """
    if not settings.VALIDATE_TWILIO_SIGNATURES:
        _LOGGER.debug("Twilio websocket signature validation disabled by config.")
        return True
    if not settings.TWILIO_AUTH_TOKEN:
        _LOGGER.error("Twilio signature validation is enabled but TWILIO_AUTH_TOKEN is empty.")
        return False

    _LOGGER.debug(
        "Validating Twilio websocket signature.",
        extra={"path": websocket.url.path, "query": websocket.url.query},
    )
    signature = websocket.headers.get("X-Twilio-Signature", "")
    query = websocket.url.query
    params = list(websocket.query_params.multi_items())
    candidate_urls = _build_candidate_urls(
        observed_url=str(websocket.url),
        configured_base_url=settings.public_stream_url,
        path=websocket.url.path,
        query=query,
    )
    _LOGGER.debug(
        "Websocket signature validation inputs prepared.",
        extra={"candidate_urls": candidate_urls, "signature_present": bool(signature)},
    )
    return _is_twilio_signature_valid(signature, settings.TWILIO_AUTH_TOKEN, candidate_urls, params)


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    """Initializes and tears down process-scoped resources.

    Args:
        _app: FastAPI app instance (unused; part of lifespan contract).
    """
    _LOGGER.debug("Voice gateway lifespan startup beginning.")
    # Boot-time observability init is optional and should not block call flow.
    if settings.DB_CONNECTION_STRING:
        try:
            _LOGGER.debug("Initializing observability DB pool on startup.")
            await init_pool()
            _LOGGER.debug("Observability DB pool initialized.")
        except Exception:
            _LOGGER.exception("Failed to initialize observability DB pool.")
    try:
        yield
    finally:
        _LOGGER.debug("Voice gateway lifespan shutdown beginning.")
        try:
            await close_pool()
            _LOGGER.debug("Observability DB pool closed.")
        except Exception:
            _LOGGER.exception("Failed to close observability DB pool.")


_configure_logging()
app = FastAPI(lifespan=_lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    """Returns a minimal liveness response for probes."""
    return {"status": "ok", "service": "voice_gateway"}


@app.post("/twilio/inbound")
@app.get("/twilio/inbound")
async def inbound(request: Request) -> PlainTextResponse:
    """Returns TwiML that instructs Twilio to open a media stream websocket.

    Args:
        request: Inbound Twilio webhook request.

    Raises:
        HTTPException: If request signature validation fails.

    Returns:
        XML response containing TwiML `<Connect><Stream>` instructions.
    """
    _LOGGER.debug(
        "Inbound Twilio webhook received.",
        extra={"method": request.method, "url": str(request.url)},
    )
    # Reject untrusted webhook traffic before returning any TwiML.
    if not await _validate_twilio_http_request(request):
        _LOGGER.debug("Inbound Twilio webhook rejected due to failed signature validation.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Twilio request signature.",
        )

    ws_url = f"{settings.public_stream_url}/twilio/stream"
    _LOGGER.debug("Building TwiML response for inbound call.", extra={"stream_url": ws_url})
    twiml = build_connect_stream_twiml(ws_url)
    _LOGGER.debug("Returning TwiML response to Twilio.", extra={"twiml_length": len(twiml)})
    return PlainTextResponse(content=twiml, media_type="text/xml")


@app.websocket("/twilio/stream")
async def twilio_stream(websocket: WebSocket) -> None:
    """Handles the Twilio media-stream websocket lifecycle.

    Args:
        websocket: Upgraded websocket connection from Twilio.
    """
    ws_url = getattr(websocket, "url", None)
    ws_client = getattr(websocket, "client", None)
    _LOGGER.debug(
        "Twilio websocket upgrade request received.",
        extra={"url": str(ws_url), "client": str(ws_client)},
    )
    # Validate the upgrade request before accepting websocket frames.
    if not _validate_twilio_ws_request(websocket):
        _LOGGER.debug("Twilio websocket rejected due to failed signature validation.")
        await websocket.close(code=1008, reason="Invalid Twilio request signature.")
        return

    _LOGGER.debug("Creating TwilioHandler for websocket lifecycle.")
    handler = TwilioHandler(websocket)
    try:
        _LOGGER.debug("Starting TwilioHandler.")
        await handler.start()
        _LOGGER.debug("Waiting for TwilioHandler completion.")
        await handler.wait_until_done()
        _LOGGER.debug("TwilioHandler completed message loop.")
    except WebSocketDisconnect:
        _LOGGER.info("Twilio websocket disconnected.")
    except Exception:
        _LOGGER.exception("Unhandled error while processing Twilio media stream.")
        raise
    finally:
        # Idempotent and safe to call even if shutdown happened earlier.
        _LOGGER.debug("Ensuring TwilioHandler shutdown in websocket finalizer.")
        await handler.shutdown()

from __future__ import annotations

import logging

_LOGGER = logging.getLogger(__name__)


def build_connect_stream_twiml(ws_url: str) -> str:
    """Builds TwiML payload that instructs Twilio to open a media stream."""
    _LOGGER.debug("Building Connect/Stream TwiML.", extra={"stream_url": ws_url})
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        "  <Connect>\n"
        f'    <Stream url="{ws_url}" />\n'
        "  </Connect>\n"
        "</Response>"
    )

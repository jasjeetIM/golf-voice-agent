from __future__ import annotations

import html
import logging

_LOGGER = logging.getLogger(__name__)


def build_connect_stream_twiml(
    ws_url: str,
    *,
    from_number: str | None = None,
    to_number: str | None = None,
) -> str:
    """Builds TwiML payload that instructs Twilio to open a media stream."""
    _LOGGER.debug(
        "Building Connect/Stream TwiML.",
        extra={
            "stream_url": ws_url,
            "has_from_number": bool(from_number),
            "has_to_number": bool(to_number),
        },
    )
    params: list[str] = []
    if from_number:
        params.append(f'      <Parameter name="from" value="{html.escape(from_number)}" />\n')
    if to_number:
        params.append(f'      <Parameter name="to" value="{html.escape(to_number)}" />\n')
    parameter_block = "".join(params)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        "  <Connect>\n"
        f'    <Stream url="{html.escape(ws_url)}">\n'
        f"{parameter_block}"
        "    </Stream>\n"
        "  </Connect>\n"
        "</Response>"
    )

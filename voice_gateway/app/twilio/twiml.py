from __future__ import annotations


def build_connect_stream_twiml(ws_url: str) -> str:
    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<Response>\n"
        "  <Connect>\n"
        f"    <Stream url=\"{ws_url}\" />\n"
        "  </Connect>\n"
        "</Response>"
    )

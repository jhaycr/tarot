"""Server-Sent Events helpers, shared by streaming endpoints.

Deliberately tiny (no sse-starlette dep): the wire format is one framing
function. Factored out so the guided-reading stream and a future live
collaborative reading (c5) share one correct writer + header set.
"""

import json


def sse(event: str, data: dict | str) -> str:
    """One SSE event: a named event line + a data line + the blank-line
    terminator. Missing the double newline makes the browser buffer forever."""
    payload = data if isinstance(data, str) else json.dumps(data)
    return f"event: {event}\ndata: {payload}\n\n"


# Response headers for a text/event-stream. X-Accel-Buffering:no is harmless with
# traefik (which doesn't buffer by default) but protects against a future
# buffering layer; Cache-Control:no-cache keeps intermediaries off the stream.
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

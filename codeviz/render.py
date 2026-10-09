"""Inline the call-graph data, styles and script into one self-contained HTML page."""

from __future__ import annotations

import base64
import gzip
import html
import json
from importlib.resources import files

_VIEWER = files("codeviz") / "viewer"
COMPRESS_ABOVE = 512 * 1024  # bytes of JSON; smaller pages keep readable plain JSON


def render(data: dict, compress: bool | None = None) -> str:
    """`compress`: gzip the data into the page (None = only when it is big)."""
    template = (_VIEWER / "index.html").read_text(encoding="utf-8")
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    packed = ""
    if compress or (compress is None and len(payload) > COMPRESS_ABOVE):
        packed = base64.b64encode(gzip.compress(payload.encode("utf-8"), compresslevel=9, mtime=0)).decode("ascii")
        payload = "null"
    # keep "</script>" (and "<!--") inside the JSON from closing the script tag
    payload = payload.replace("</", "<\\/").replace("<!--", "\\u003c!--")
    return (template
            .replace("/*__DATA_GZ__*/", packed)
            .replace("/*__STYLE__*/", (_VIEWER / "style.css").read_text(encoding="utf-8"))
            .replace("/*__APP__*/", (_VIEWER / "app.js").read_text(encoding="utf-8"))
            .replace("__TITLE__", html.escape(data["name"]))
            .replace("/*__DATA__*/null", payload))

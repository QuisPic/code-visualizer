"""Inline the call-graph data, styles and script into one self-contained HTML page."""

from __future__ import annotations

import html
import json
from importlib.resources import files

_VIEWER = files("codeviz") / "viewer"


def render(data: dict) -> str:
    template = (_VIEWER / "index.html").read_text(encoding="utf-8")
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    # keep "</script>" (and "<!--") inside the JSON from closing the script tag
    payload = payload.replace("</", "<\\/").replace("<!--", "\\u003c!--")
    return (template
            .replace("/*__STYLE__*/", (_VIEWER / "style.css").read_text(encoding="utf-8"))
            .replace("/*__APP__*/", (_VIEWER / "app.js").read_text(encoding="utf-8"))
            .replace("__TITLE__", html.escape(data["name"]))
            .replace("/*__DATA__*/null", payload))

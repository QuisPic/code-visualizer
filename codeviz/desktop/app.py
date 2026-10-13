"""Desktop app: a native window (pywebview) on a local HTTP server that scans folders and serves the viewer.

The start page and the viewer talk to the server over HTTP (`api/...`), so the same pages also work in a plain
browser (`--browser`). Only the native folder dialog needs the window. Everything is served under a random path
prefix on 127.0.0.1, and requests with any other Host are refused, so other pages in a browser can't drive it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
import tempfile
import threading
import traceback
import webbrowser
from urllib.parse import quote
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path

from ..project import DEFAULT_EXCLUDES, build, source_link
from ..render import render

_HERE = files("codeviz") / "desktop"
_VIEWER = files("codeviz") / "viewer"
PORT = 47823  # fixed when free, so bookmarks and settings in localStorage (per origin) survive restarts
MAX_RECENT = 12


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "codeviz"


def use_bundled_grammars() -> None:
    """In the packaged app, load tree-sitter grammars from the bundle instead of downloading them."""
    bundled = Path(getattr(sys, "_MEIPASS", "")) / "grammars"
    if getattr(sys, "frozen", False) and bundled.is_dir():
        import tree_sitter_language_pack as tslp
        tslp.configure(tslp.PackConfig(cache_dir=str(bundled)))


class Recent:
    """Recently opened folders, newest first, kept in <config>/recent.json."""

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()

    def load(self) -> list[str]:
        try:
            items = json.loads(self.path.read_text(encoding="utf-8"))
            return [p for p in items if isinstance(p, str)]
        except (OSError, ValueError):
            return []

    def _save(self, items: list[str]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(items[:MAX_RECENT], indent=1), encoding="utf-8")
        except OSError:
            pass

    def add(self, folder: str) -> None:
        with self.lock:
            self._save([folder] + [p for p in self.load() if p != folder])

    def remove(self, folder: str) -> None:
        with self.lock:
            self._save([p for p in self.load() if p != folder])


class App:
    """Scan jobs, the pages they produced, and the window (None in --browser mode)."""

    def __init__(self, recent: Recent):
        self.recent = recent
        self.window = None
        self.jobs: dict[str, dict] = {}
        self.pages: dict[str, dict] = {}  # key -> {"path", "html"}
        self.lock = threading.Lock()

    def pick_folder(self) -> str | None:
        if self.window is None:
            return None
        import webview
        start = next(iter(self.recent.load()), "")
        res = self.window.create_file_dialog(webview.FileDialog.FOLDER, directory=str(Path(start).parent) if start else "")
        return (res[0] if isinstance(res, (list, tuple)) else res) if res else None

    def start_scan(self, folder: str) -> str:
        job_id = secrets.token_hex(6)
        self.jobs[job_id] = {"state": "running", "done": 0, "total": 0, "path": folder}
        threading.Thread(target=self._scan, args=(job_id, folder), daemon=True).start()
        return job_id

    def _scan(self, job_id: str, folder: str) -> None:
        job = self.jobs[job_id]
        try:
            root = Path(folder).expanduser().resolve()
            if not root.is_dir():
                raise ValueError(f"{folder} is not a folder")

            def progress(done: int, total: int) -> None:
                job["done"], job["total"] = done, total

            data = build(root, root.name or str(root), list(DEFAULT_EXCLUDES), quiet=True,
                         link=source_link(root), progress=progress)
            if not data["files"]:
                raise ValueError("No supported source files found in this folder.")
            key = hashlib.sha1(str(root).encode("utf-8")).hexdigest()[:12]
            page = inject(render(data, compress=False), str(root))
            with self.lock:
                self.pages[key] = {"path": str(root), "html": page.encode("utf-8")}
            self.recent.add(str(root))
            if self.window is not None:
                self.window.set_title(f"{data['name']} · codeviz")
            s = data["stats"]
            job.update(state="done", url=f"view/{key}/", stats=s)
        except BaseException as exc:  # SystemExit from project code included: report it, keep the app alive
            job.update(state="error", error=str(exc) or exc.__class__.__name__,
                       detail="" if isinstance(exc, (ValueError, SystemExit)) else traceback.format_exc())


def inject(page: str, folder: str) -> str:
    """Add the desktop toolbar (open another folder, rescan) to a rendered viewer page."""
    script = (_HERE / "inject.js").read_text(encoding="utf-8")
    cfg = json.dumps({"path": folder}).replace("</", "<\\/")
    extra = f"<script>window.CODEVIZ_DESKTOP = {cfg};\n{script}</script>\n"
    i = page.rfind("</body>")
    return page[:i] + extra + page[i:]


def start_page() -> bytes:
    page = (_HERE / "start.html").read_text(encoding="utf-8")
    return page.replace("/*__STYLE__*/", (_VIEWER / "style.css").read_text(encoding="utf-8")).encode("utf-8")


def make_server(app: App, port: int = PORT) -> tuple[ThreadingHTTPServer, str]:
    """Start the server on a background thread; returns it and the start page URL."""
    token = secrets.token_urlsafe(12)
    prefix = f"/{token}/"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype + ("; charset=utf-8" if "json" in ctype or "html" in ctype else ""))
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200) -> None:
            self._send(code, json.dumps(obj).encode("utf-8"))

        def _route(self) -> str | None:
            host = self.headers.get("Host", "")
            if host not in (f"127.0.0.1:{self.server.server_address[1]}", f"localhost:{self.server.server_address[1]}"):
                self._send(403, b"forbidden", "text/plain")
                return None
            path = self.path.split("?", 1)[0]
            if path == prefix.rstrip("/"):
                path = prefix
            if not path.startswith(prefix):
                self._send(404, b"not found", "text/plain")
                return None
            return path[len(prefix):]

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            try:
                return json.loads(self.rfile.read(n) or b"{}") if n else {}
            except ValueError:
                return {}

        def do_GET(self) -> None:
            route = self._route()
            if route is None:
                return
            if route in ("", "index.html"):
                self._send(200, start_page(), "text/html")
            elif route == "api/recent":
                items = self.server.app.recent.load()
                self._json([{"path": p, "name": Path(p).name or p, "exists": Path(p).is_dir()} for p in items])
            elif route.startswith("api/job/"):
                job = self.server.app.jobs.get(route[len("api/job/"):])
                self._json(job or {"state": "error", "error": "unknown job"}, 200 if job else 404)
            elif route.startswith("view/"):
                page = self.server.app.pages.get(route[len("view/"):].strip("/"))
                if page:
                    self._send(200, page["html"], "text/html")
                else:  # e.g. after a restart: back to the start page
                    self.send_response(302)
                    self.send_header("Location", prefix)
                    self.end_headers()
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self) -> None:
            route = self._route()
            if route is None:
                return
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                self._send(415, b"json only", "text/plain")  # forces a CORS preflight for cross-site requests
                return
            body, app = self._body(), self.server.app
            if route == "api/pick":
                if app.window is None:
                    self._json({"unsupported": True})
                else:
                    self._json({"path": app.pick_folder()})
            elif route == "api/scan":
                folder = str(body.get("path") or "").strip()
                if not folder:
                    self._json({"error": "no folder given"}, 400)
                else:
                    self._json({"job": app.start_scan(folder)})
            elif route == "api/forget":
                app.recent.remove(str(body.get("path") or ""))
                self._json({"ok": True})
            else:
                self._send(404, b"not found", "text/plain")

    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    server.app = app
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}{prefix}"


def self_test() -> int:
    """Scan a small generated project with the bundled grammars; used by CI on the packaged app."""
    from ..languages import BY_EXTENSION
    from tree_sitter_language_pack import get_parser

    for name in sorted({lang.name for lang in BY_EXTENSION.values()}):
        get_parser(name)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "a.py").write_text("def f():\n    g()\n\ndef g():\n    pass\n")
        (root / "b.cpp").write_text("int h() { return k(); }\nint k() { return 1; }\n")
        (root / "c.ts").write_text("export function m() { return n(); }\nfunction n() { return 2; }\n")
        data = build(root, "selftest", list(DEFAULT_EXCLUDES), quiet=True)
        page = inject(render(data, compress=False), str(root))
    s = data["stats"]
    ok = s["files"] == 3 and s["functions"] == 6 and s["resolved"] == 3 and "CODEVIZ_DESKTOP" in page
    print(f"self-test {'ok' if ok else 'FAILED'}: {s}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    for name in ("stdout", "stderr"):  # windowed builds on Windows have no console streams
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w"))
    ap = argparse.ArgumentParser(prog="codeviz-app", description="Open a folder and browse its call graph.")
    ap.add_argument("folder", nargs="?", help="folder to open right away")
    ap.add_argument("--browser", action="store_true", help="use the default web browser instead of a window")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--smoke-test", metavar="RESULT_FILE", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    use_bundled_grammars()
    if args.self_test:
        return self_test()

    app = App(Recent(config_dir() / "recent.json"))
    server, url = make_server(app, args.port)
    if args.folder:
        url += "#open=" + quote(str(Path(args.folder).expanduser().resolve()), safe="")

    if sys.platform.startswith("linux") and not args.browser:
        if getattr(sys, "frozen", False):
            os.environ.setdefault("PYWEBVIEW_GUI", "qt")  # the packaged app bundles Qt WebEngine, not GTK
        reason = linux_sandbox_problem()
        if reason and not args.smoke_test:
            print(f"codeviz: the app window can't start here ({reason}); using the web browser instead",
                  file=sys.stderr)
            args.browser = True

    if args.browser:
        return run_in_browser(url)

    import webview

    webview.settings["ALLOW_DOWNLOADS"] = True  # graph export (SVG / PNG / Mermaid)
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    app.window = webview.create_window("codeviz", url, width=1400, height=900, min_size=(720, 480),
                                       text_select=True, zoomable=True)
    storage = config_dir() / "webview"
    storage.mkdir(parents=True, exist_ok=True)
    result: list[str] = []
    if args.smoke_test:
        threading.Thread(target=smoke_test, args=(app.window, args.smoke_test, result), daemon=True).start()
    try:
        webview.start(private_mode=False, storage_path=str(storage))
    except webview.errors.WebViewException as exc:  # no Qt or GTK web view (Linux without them installed)
        if args.smoke_test:
            raise
        print(f"codeviz: can't open a window ({exc}); using the web browser instead", file=sys.stderr)
        app.window = None
        return run_in_browser(url)
    server.shutdown()
    return 0 if not args.smoke_test or result == ["ok"] else 1


def run_in_browser(url: str) -> int:
    print(f"codeviz is running at {url}  (Ctrl+C to stop)")
    webbrowser.open(url)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    return 0


def linux_sandbox_problem() -> str:
    """Why Qt WebEngine's Chromium sandbox can't start on this Linux system, or "" when it can.

    The sandbox needs unprivileged user namespaces, which some distros block for apps without an AppArmor
    profile (Ubuntu 24.04+), and Chromium refuses to run as root. Qt WebEngine then aborts, so the app opens
    the user's browser instead. Setting QTWEBENGINE_DISABLE_SANDBOX=1 yourself forces the window.
    """
    if os.environ.get("PYWEBVIEW_GUI") != "qt" or os.environ.get("QTWEBENGINE_DISABLE_SANDBOX") \
            or "--no-sandbox" in os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", ""):
        return ""

    def sysctl(name: str) -> str:
        try:
            return Path("/proc/sys/kernel", name).read_text().strip()
        except OSError:
            return ""

    if os.geteuid() == 0:
        return "running as root"
    if sysctl("apparmor_restrict_unprivileged_userns") == "1" or sysctl("unprivileged_userns_clone") == "0":
        return "unprivileged user namespaces are restricted"
    return ""


def smoke_test(window, result_file: str, result: list[str]) -> None:
    """CI check of the real window: wait until the viewer shows the folder's explorer tree, then close."""
    import time

    outcome = "timed out waiting for the viewer"
    deadline = time.time() + 120
    while time.time() < deadline:
        time.sleep(1)
        try:
            n = window.evaluate_js("document.querySelectorAll('#explorer li').length || 0")
            err = window.evaluate_js("(document.querySelector('.status.error') || {}).textContent || ''")
        except Exception as exc:  # window not ready yet
            outcome = f"evaluate_js failed: {exc}"
            continue
        if err:
            outcome = f"scan failed: {err}"
            break
        if n:
            outcome = "ok"
            break
    result.append(outcome)
    Path(result_file).write_text(outcome + "\n", encoding="utf-8")
    window.destroy()

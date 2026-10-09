"""Find source files in a directory or git repo and build the call-graph data for the viewer."""

from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from .extract import FileInfo, extract_file
from .languages import BY_EXTENSION, Language
from .resolve import Resolver

DEFAULT_EXCLUDES = [
    ".git", ".hg", ".svn", "node_modules", "bower_components", "vendor", "third_party", "third-party",
    "build", "dist", "out", "target", "__pycache__", ".venv", "venv", ".tox", ".mypy_cache",
    "*.min.js", "*.bundle.js", "*.map",
]
MAX_FILE_BYTES = 1_000_000


def is_git_url(source: str) -> bool:
    return source.startswith(("http://", "https://", "git@", "ssh://", "git://")) or (
        source.endswith(".git") and not Path(source).exists())


@contextmanager
def checkout(source: str, ref: str | None = None):
    """Yield a local directory for `source`, cloning it to a temp dir when it is a git URL."""
    if not is_git_url(source):
        path = Path(source).expanduser().resolve()
        if not path.is_dir():
            raise SystemExit(f"error: {source} is not a directory or git URL")
        yield path
        return
    tmp = Path(tempfile.mkdtemp(prefix="codeviz-"))
    try:
        cmd = ["git", "clone", "--depth", "1", "--quiet"]
        if ref:
            cmd += ["--branch", ref]
        print(f"cloning {source} ...", file=sys.stderr)
        subprocess.run(cmd + [source, str(tmp / "repo")], check=True)
        yield tmp / "repo"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _excluded(rel: str, patterns: list[str]) -> bool:
    parts = rel.split("/")
    for pat in patterns:
        if "/" in pat:
            if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(rel, pat.rstrip("/") + "/*"):
                return True
        elif any(fnmatch.fnmatch(p, pat) for p in parts):
            return True
    return False


def list_files(root: Path, excludes: list[str]) -> list[str]:
    """Source files under root (relative, posix). Uses `git ls-files` when root is a git work tree."""
    rels: list[str] | None = None
    if (root / ".git").exists():
        try:
            found: set[str] = set()
            for args in (["--cached", "--recurse-submodules"], ["--others", "--exclude-standard"]):
                out = subprocess.run(["git", "-C", str(root), "ls-files", "-z", *args],
                                     capture_output=True, check=True).stdout
                found.update(p for p in out.decode("utf-8", "replace").split("\0") if p)
            rels = list(found)
        except (subprocess.CalledProcessError, FileNotFoundError):
            rels = None
    if rels is None:
        rels = []
        for dirpath, dirnames, filenames in os.walk(root):
            rel_dir = Path(dirpath).relative_to(root).as_posix()
            dirnames[:] = [d for d in dirnames
                           if not _excluded(d if rel_dir == "." else f"{rel_dir}/{d}", excludes)]
            rels += [f if rel_dir == "." else f"{rel_dir}/{f}" for f in filenames]
    return sorted(r for r in rels
                  if Path(r).suffix.lower() in BY_EXTENSION and not _excluded(r, excludes)
                  and (root / r).is_file())


def _parsers():
    from tree_sitter_language_pack import get_parser

    cache: dict[str, object] = {}

    def get(lang: Language):
        if lang.name not in cache:
            cache[lang.name] = get_parser(lang.name)
        return cache[lang.name]

    return get


def build(root: Path, name: str, excludes: list[str], quiet: bool = False) -> dict:
    t0 = time.time()
    get_parser = _parsers()
    files: list[FileInfo] = []
    skipped = 0
    for rel in list_files(root, excludes):
        path = root / rel
        if path.stat().st_size > MAX_FILE_BYTES:
            skipped += 1
            continue
        lang = BY_EXTENSION[path.suffix.lower()]
        try:
            files.append(extract_file(lang, get_parser(lang), rel, path.read_bytes()))
        except Exception as exc:  # a broken grammar download or odd file shouldn't sink the run
            skipped += 1
            if not quiet:
                print(f"warning: skipped {rel}: {exc}", file=sys.stderr)

    resolver = Resolver(files)
    funcs = resolver.functions
    file_index = {f.path: i for i, f in enumerate(files)}
    out_funcs = []
    counts = {"calls": 0, "resolved": 0, "external": 0}
    for i, fn in enumerate(funcs):
        calls = []
        for call in fn.calls:
            targets, conf = resolver.resolve(fn, call)
            counts["calls"] += 1
            counts["resolved" if targets else "external"] += 1
            entry = {"n": call.name, "l": call.line, "c": call.col}
            if call.qualifier:
                entry["q"] = call.qualifier
            if targets:
                entry["t"] = targets
                entry["x"] = conf[0]  # h | l | a
            calls.append(entry)
        record = {
            "id": i, "n": fn.name, "s": "::".join(fn.scope) if fn.lang.family in ("c", "rust", "php")
            else ".".join(fn.scope), "f": file_index[fn.path], "l": fn.start, "e": fn.end, "k": fn.kind,
            "code": fn.code, "calls": calls,
        }
        if fn.doc:
            record["d"] = fn.doc
        out_funcs.append(record)
    data = {
        "name": name,
        "generated": time.strftime("%Y-%m-%d %H:%M"),
        "files": [{"p": f.path, "lang": f.lang.name, "lines": f.lines} for f in files],
        "funcs": out_funcs,
        "stats": {"files": len(files), "functions": sum(1 for f in funcs if f.kind != "toplevel"),
                  "skipped": skipped, **counts, "seconds": round(time.time() - t0, 2)},
    }
    return data

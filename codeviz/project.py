"""Find source files in a directory or git repo and build the call-graph data for the viewer."""

from __future__ import annotations

import fnmatch
import os
import re
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


_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)


def _git(root: Path, *args: str) -> str | None:
    try:
        res = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, errors="replace")
    except OSError:
        return None
    return res.stdout if res.returncode == 0 else None


def changed_lines(root: Path, ref: str) -> tuple[dict[str, set[int]], dict[str, set[int]]]:
    """Lines changed since `ref` (where the current branch left it, uncommitted edits included).

    Returns (touched, added): touched lines per file (a deletion touches the line after it) and
    the subset that is newly added, used to tell new functions from modified ones.
    """
    if _git(root, "rev-parse", "--verify", "--quiet", ref + "^{commit}") is None:
        # a shallow clone (git URL) doesn't have the ref yet
        _git(root, "fetch", "--quiet", "--depth", "200", "origin", ref)
        _git(root, "fetch", "--quiet", "--deepen", "200")
        if _git(root, "rev-parse", "--verify", "--quiet", "FETCH_HEAD") is not None and \
                _git(root, "rev-parse", "--verify", "--quiet", ref + "^{commit}") is None:
            ref = "FETCH_HEAD"
    base = (_git(root, "merge-base", ref, "HEAD") or "").strip() or ref
    diff = _git(root, "diff", "--unified=0", "--no-color", "--no-ext-diff", "--no-renames", base, "--")
    if diff is None:
        raise SystemExit(f"error: can't diff against {ref!r} (not a git repo, or unknown branch/commit)")
    touched: dict[str, set[int]] = {}
    added: dict[str, set[int]] = {}
    for chunk in re.split(r"^diff --git ", diff, flags=re.MULTILINE)[1:]:
        m = re.search(r"^\+\+\+ b/(.+)$", chunk, re.MULTILINE)
        if not m:
            continue  # deleted file
        path = m.group(1)
        t, a = touched.setdefault(path, set()), added.setdefault(path, set())
        new_file = "\nnew file mode" in chunk.split("@@", 1)[0]
        for h in _HUNK.finditer(chunk):
            start, count = int(h.group(1)), int(h.group(2) or 1)
            if count == 0:
                t.add(max(start, 1))  # pure deletion after line `start`
            else:
                lines = range(start, start + count)
                t.update(lines)
                if new_file:
                    a.update(lines)
                else:
                    # lines starting with "+" in this hunk are additions; a hunk that also removes
                    # lines is a modification, so only count it as added when nothing was removed
                    body = chunk[h.end():].split("\n@@", 1)[0]
                    if not re.search(r"^-", body, re.MULTILINE):
                        a.update(lines)
    for path in (_git(root, "ls-files", "--others", "--exclude-standard") or "").splitlines():
        n = sum(1 for _ in open(root / path, "rb")) if (root / path).is_file() else 0
        touched[path] = added[path] = set(range(1, n + 1))
    return touched, added


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


# Line-range URL formats by host; {path} is relative to the repository root.
_LINK_STYLES = {
    "github": "{repo}/blob/{sha}/{path}#L{line}-L{end}",
    "gitlab": "{repo}/-/blob/{sha}/{path}#L{line}-{end}",
    "bitbucket": "{repo}/src/{sha}/{path}#lines-{line}:{end}",
    "gitea": "{repo}/src/commit/{sha}/{path}#L{line}-L{end}",
}


def _web_url(remote: str) -> tuple[str, str] | None:
    """(https URL, link style) for a git remote on a known host, or None."""
    m = (re.match(r"^[\w.-]+@([^:/]+):(.+)$", remote)  # git@host:owner/repo
         or re.match(r"^(?:ssh|git|https?)://(?:[^@/]+@)?([^/:]+)(?::\d+)?/(.+)$", remote))
    if not m:
        return None
    host, repo = m.group(1).lower(), m.group(2).removesuffix("/").removesuffix(".git")
    style = next((s for s in _LINK_STYLES if s in host), "gitea" if host == "codeberg.org" else None)
    return (f"https://{host}/{repo}", style) if style else None


def source_link(root: Path) -> str | None:
    """URL template ({path}, {line}, {end}) pointing at the scanned commit on the repo's web host."""
    def git(*args: str) -> str:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                              check=True).stdout.strip()
    try:
        remote, sha, prefix = git("remote", "get-url", "origin"), git("rev-parse", "HEAD"), git("rev-parse", "--show-prefix")
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    web = _web_url(remote)
    if not web:
        return None
    url, style = web
    return _LINK_STYLES[style].replace("{repo}", url).replace("{sha}", sha).replace("{path}", prefix + "{path}")


def build(root: Path, name: str, excludes: list[str], quiet: bool = False, changed_since: str | None = None,
          link: str | None = None) -> dict:
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

    touched, added = changed_lines(root, changed_since) if changed_since else ({}, {})
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
        if fn.complexity > 1:
            record["cx"] = fn.complexity
        lines = touched.get(fn.path)
        if lines and fn.kind != "toplevel" and any(fn.start <= ln <= fn.end for ln in lines):
            span = range(fn.start, fn.end + 1)
            record["ch"] = "n" if all(ln in added[fn.path] for ln in span) else "m"  # new | modified
        out_funcs.append(record)
    data = {
        "name": name,
        "generated": time.strftime("%Y-%m-%d %H:%M"),
        "files": [{"p": f.path, "lang": f.lang.name, "lines": f.lines} for f in files],
        "funcs": out_funcs,
        **({"changed": {"ref": changed_since,
                        "functions": sum(1 for f in out_funcs if "ch" in f)}} if changed_since else {}),
        "stats": {"files": len(files), "functions": sum(1 for f in funcs if f.kind != "toplevel"),
                  "skipped": skipped, **counts, "seconds": round(time.time() - t0, 2)},
    }
    if link:
        data["link"] = link
    return data

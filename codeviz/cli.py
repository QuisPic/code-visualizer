"""Command line entry point: `codeviz <dir-or-git-url> [-o out.html]`."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from .project import DEFAULT_EXCLUDES, build, checkout, is_git_url
from .render import render


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="codeviz",
        description="Generate an interactive HTML call tree for a directory or git repository.")
    ap.add_argument("source", help="local directory or git URL (https://..., git@...)")
    ap.add_argument("-o", "--output", help="output HTML file (default: <name>-codeviz.html)")
    ap.add_argument("--ref", help="branch or tag to clone when SOURCE is a git URL")
    ap.add_argument("--name", help="project name shown in the page (default: directory/repo name)")
    ap.add_argument("-x", "--exclude", action="append", default=[], metavar="GLOB",
                    help="exclude files or directories matching GLOB (repeatable), e.g. -x tests -x 'docs/*'")
    ap.add_argument("--no-default-excludes", action="store_true",
                    help=f"don't skip the usual vendored/build dirs ({', '.join(DEFAULT_EXCLUDES[:6])}, ...)")
    ap.add_argument("--json", action="store_true", help="also write the raw call graph as <output>.json")
    ap.add_argument("--open", action="store_true", help="open the result in a browser")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args(argv)

    excludes = ([] if args.no_default_excludes else list(DEFAULT_EXCLUDES)) + args.exclude
    name = args.name or (args.source.rstrip("/").split("/")[-1].removesuffix(".git") if is_git_url(args.source)
                         else Path(args.source).expanduser().resolve().name)
    with checkout(args.source, args.ref) as root:
        data = build(root, name, excludes, quiet=args.quiet)

    out = Path(args.output or f"{name}-codeviz.html")
    out.write_text(render(data), encoding="utf-8")
    if args.json:
        import json
        out.with_suffix(".json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    s = data["stats"]
    if not args.quiet:
        print(f"{s['files']} files, {s['functions']} functions, {s['calls']} calls "
              f"({s['resolved']} linked) in {s['seconds']}s -> {out}", file=sys.stderr)
    if args.open:
        webbrowser.open(out.resolve().as_uri())
    return 0

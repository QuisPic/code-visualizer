"""Command line entry point: `codeviz <dir-or-git-url> [-o out.html]`."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from .project import DEFAULT_EXCLUDES, build, checkout, is_git_url, source_link
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
    ap.add_argument("--changed-since", metavar="REF",
                    help="mark functions changed since a branch/commit (e.g. main), uncommitted edits included")
    ap.add_argument("--json", action="store_true", help="also write the raw call graph as <output>.json")
    ap.add_argument("--no-compress", action="store_true",
                    help="keep the data as plain JSON in the page even when it is big (larger file)")
    ap.add_argument("--open", action="store_true", help="open the result in a browser")
    ap.add_argument("--link", metavar="TEMPLATE",
                    help="URL for 'open in browser' links, with {path}, {line}, {end} and {root} "
                         "(default: the git remote's GitHub/GitLab/Bitbucket page for the scanned commit)")
    ap.add_argument("--no-link", action="store_true", help="don't add links to the repository's web page")
    ap.add_argument("--churn", nargs="?", const="1 year", metavar="SINCE",
                    help="count how often each file changed in git since SINCE (default: 1 year) and list "
                         "hotspots: big files that change a lot")
    ap.add_argument("-q", "--quiet", action="store_true")
    args = ap.parse_args(argv)

    excludes = ([] if args.no_default_excludes else list(DEFAULT_EXCLUDES)) + args.exclude
    name = args.name or (args.source.rstrip("/").split("/")[-1].removesuffix(".git") if is_git_url(args.source)
                         else Path(args.source).expanduser().resolve().name)
    with checkout(args.source, args.ref) as root:
        link = None if args.no_link else args.link or source_link(root)
        if link:
            link = link.replace("{root}", root.as_posix())  # e.g. vscode://file{root}/{path}:{line}
        data = build(root, name, excludes, quiet=args.quiet, changed_since=args.changed_since,
                     link=link, churn_since=args.churn)

    out = Path(args.output or f"{name}-codeviz.html")
    out.write_text(render(data, compress=False if args.no_compress else None), encoding="utf-8")
    if args.json:
        import json
        out.with_suffix(".json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    s = data["stats"]
    if not args.quiet:
        print(f"{s['files']} files, {s['functions']} functions, {s['calls']} calls "
              f"({s['resolved']} linked) in {s['seconds']}s -> {out}", file=sys.stderr)
        if "changed" in data:
            print(f"{data['changed']['functions']} functions changed since {args.changed_since}", file=sys.stderr)
    if args.open:
        webbrowser.open(out.resolve().as_uri())
    return 0

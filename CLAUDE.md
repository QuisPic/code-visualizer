# CLAUDE.md

codeviz is a Python CLI that turns a directory or git repo into **one self-contained HTML page**:
an explorer tree of every function, a call graph you click through (callees and callers), and
linked, highlighted source. See `README.md` for the user-facing feature list and options.

## Commands

```
pip install -e '.[test]'          # Python 3.10+; needs network once per language (grammar download)
pytest                            # tests/test_codeviz.py, runs against tests/fixtures/mixed
codeviz <dir-or-git-url> -o out.html [--json] [--open]   # or: python -m codeviz ...
```

There is no linter, formatter config, JS build step or CI. Generated `*-codeviz.html` /
`*-codeviz.json` files are git-ignored; don't commit them.

## Pipeline

`cli.py` → `project.build()` → `render.render()` → one HTML file.

| file | role |
|---|---|
| `codeviz/cli.py` | argparse entry point (`codeviz` console script, `__main__.py`) |
| `codeviz/project.py` | `checkout()` (shallow-clones git URLs to a temp dir), `list_files()` (uses `git ls-files --recurse-submodules` in a work tree, else `os.walk` + `DEFAULT_EXCLUDES`), `build()` (extract + resolve → JSON-able dict) |
| `codeviz/languages.py` | one `Language` per grammar: extensions, tree-sitter node types for functions/scopes/calls, constructor and `self` names. `family` decides which languages may call each other (c↔cpp, js↔ts↔tsx) |
| `codeviz/extract.py` | walks a tree-sitter tree into `FileInfo` / `Function` / `Call` dataclasses; each file also gets a `(top level)` pseudo-function (`kind="toplevel"`) for module-level calls |
| `codeviz/resolve.py` | `Resolver`: name-based call linking, no type inference. Candidates with the same name are scored (same class, qualifier match, same file, `.h`/`.cpp` pair, imports, directory distance); returns confidence `high` / `low` / `ambiguous` |
| `codeviz/render.py` | inlines `viewer/style.css`, `viewer/app.js` and the JSON into `viewer/index.html` placeholders (`/*__STYLE__*/`, `/*__APP__*/`, `/*__DATA__*/null`, `__TITLE__`), escaping `</` and `<!--` |
| `codeviz/viewer/` | the page: plain HTML/CSS/vanilla JS in one IIFE, no framework, no CDN, no build. Reads the `DATA` global |

### Data format (`build()` output, the `DATA` global, `--json`)

Keys are deliberately short to keep pages small. `files[]`: `{p: path, lang, lines}`.
`funcs[]` (index = id): `{id, n: name, s: scope ("::"-joined for c/rust/php, else "."),
f: file index, l/e: start/end line, k: kind, code, d?: doc comment / docstring, calls[]}`. Each call:
`{n: name, l: line, c: column, q?: qualifier, t?: [target ids], x?: "h"|"l"|"a"}`. A call with
no `t` is external. `stats` holds counts. Changing a key means changing `project.py`,
`viewer/app.js` and the tests together.

## Conventions

- Output must stay **one offline file**: no network requests, external scripts or fonts in the
  viewer. New viewer files must be inlined by `render.py` and covered by
  `[tool.setuptools.package-data]`.
- Viewer state lives in the URL hash (`#/`, `#/f/<id>`, `#/f/<id>/in` for callers, `#/f/<id>/both`,
  `#/f/<id>/impact`, `#/path/<from>/<to>`) so back/forward works; user prefs persist in
  `localStorage["codeviz-prefs"]`, bookmarks and recent functions in `localStorage["codeviz-pins:<project>"]`
  as `file|qualified name|line` keys, since ids change between runs (wrap access in try/catch).
- Adding a language: add a `Language` to `languages.py` (node type names come from that
  grammar in `tree-sitter-language-pack`), handle any odd name/qualifier shapes in `extract.py`,
  add a file to `tests/fixtures/mixed/` and an assertion in `tests/test_codeviz.py`.
- Resolution changes: add a fixture case asserting the exact qualified target
  (`targets(find(caller), callee) == [...]`); external calls must stay `[]`. Prefer leaving a
  call unresolved or `low` over a confident wrong link.
- Code style: `from __future__ import annotations`, type hints, dataclasses, module docstring
  per file, ~110-char lines, short comments only where the reason isn't obvious.
- One extraction failure must not abort a run: `build()` warns and skips the file.

## Testing against a real repo

The real-world test target is the private repo **QuisPic/3d-surface** (C++ After Effects plugin,
ExtendScript `.jsx`, some Python). Its `engine` submodule (QuisPic/plugin-engine) is not
cloned by default. After a change to extraction, resolution or the viewer, regenerate and open it:

```
codeviz /path/to/3d-surface -o 3d-surface-codeviz.html
```

Check the printed `files / functions / calls (linked)` summary against the previous run, then
look at the page in a browser (Chromium + Playwright work for screenshots). Pytest only covers
the Python side; viewer changes need this manual check.

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

There is no linter, formatter config or JS build step. CI (`.github/workflows/desktop.yml`) runs pytest
and builds the desktop app on Windows, macOS and Linux (an AppImage with a Qt web view). Generated `*-codeviz.html` /
`*-codeviz.json` files are git-ignored; don't commit them.

## Pipeline

`cli.py` → `project.build()` → `render.render()` → one HTML file.

| file | role |
|---|---|
| `codeviz/cli.py` | argparse entry point (`codeviz` console script, `__main__.py`) |
| `codeviz/project.py` | `checkout()` (shallow-clones git URLs to a temp dir), `list_files()` (uses `git ls-files --recurse-submodules` in a work tree, else `os.walk` + `DEFAULT_EXCLUDES`), `build()` (extract + resolve → JSON-able dict) |
| `codeviz/languages.py` | one `Language` per grammar: extensions, tree-sitter node types for functions/scopes/calls, constructor and `self` names. `family` decides which languages may call each other (c↔cpp, js↔ts↔tsx) |
| `codeviz/extract.py` | walks a tree-sitter tree into `FileInfo` / `Function` / `Call` dataclasses; each file also gets a `(top level)` pseudo-function (`kind="toplevel"`) for module-level calls |
| `codeviz/resolve.py` | `Resolver`: name-based call linking, no type inference. Candidates with the same name are scored (same class, qualifier match, same file, `.h`/`.cpp` pair, imports, directory distance); returns confidence `high` / `low` / `ambiguous`. Python and JS/TS imports (`FileInfo.bindings`) are checked first and link an imported name or `module.f()` to the file it came from |
| `codeviz/render.py` | inlines `viewer/style.css`, `viewer/app.js` and the JSON into `viewer/index.html` placeholders (`/*__STYLE__*/`, `/*__APP__*/`, `/*__DATA__*/null`, `/*__DATA_GZ__*/`, `__TITLE__`), escaping `</` and `<!--`. JSON over 512 KB goes in gzipped + base64 (`DATA_GZ`) instead; `--no-compress` turns that off |
| `codeviz/desktop/` | desktop app (`codeviz-app`): a pywebview window on a local HTTP server (`app.py`) serving `start.html` (folder picker, recent folders) and rendered viewer pages with `inject.js` added (Open… / Rescan buttons). Pages talk to the server over `api/...`, so `--browser` works without a window. Packaged with `packaging/` (PyInstaller spec, Inno Setup, bundled grammars from `fetch_grammars.py`); the packaged app's `--self-test` / `--smoke-test` run in CI |
| `codeviz/viewer/` | the page: plain HTML/CSS/vanilla JS in one IIFE, no framework, no CDN, no build. `app.js` runs inside `codeviz(DATA)`, called by a loader in `index.html` once the data is ready (unpacked with `DecompressionStream` when gzipped) |

### Data format (`build()` output, the `DATA` global, `--json`)

Keys are deliberately short to keep pages small. `files[]`: `{p: path, lang, lines, cc?: commits since --churn date}`.
`funcs[]` (index = id): `{id, n: name, s: scope ("::"-joined for c/rust/php, else "."),
f: file index, l/e: start/end line, k: kind, code, d?: doc comment / docstring, cx?: cyclomatic
complexity (omitted when 1), calls[]}`. Each call:
`{n: name, l: line, c: column, q?: qualifier, t?: [target ids], x?: "h"|"l"|"a", r?: 1}`
(`r`: a callback passed by name, not a call; only kept when linked). With `--changed-since`, changed functions get `ch: "n"|"m"` (new / modified) and the
top level gets `changed: {ref, functions}`. A call with
no `t` is external. `stats` holds counts; with `--churn`, `churn: {since, commits}`. Optional top-level `link` is a URL template (`{path}`, `{line}`,
`{end}`) for the repo's web page, from `project.source_link()` or `--link`. Changing a key means changing `project.py`,
`viewer/app.js` and the tests together.

## Conventions

- Output must stay **one offline file**: no network requests, external scripts or fonts in the
  viewer. New viewer files must be inlined by `render.py` and covered by
  `[tool.setuptools.package-data]`.
- Viewer state lives in the URL hash (`#/`, `#/f/<id>`, `#/f/<id>/in` for callers, `#/f/<id>/both`,
  `#/f/<id>/impact`, `#/path/<from>/<to>`, `#/deps/<depth>`,
  `#/class/<file index>/<scope>`) so back/forward works; user prefs persist in
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

Pytest only uses small fixtures, so after a change to extraction, resolution or the viewer, also run
codeviz on a real, mid-sized repo (for example flask, express or redis) and open the page:

```
codeviz /path/to/some-repo -o some-repo-codeviz.html
```

Check the printed `files / functions / calls (linked)` summary against the previous run, then
look at the page in a browser (Chromium + Playwright work for screenshots). Pytest only covers
the Python side; viewer changes need this manual check.

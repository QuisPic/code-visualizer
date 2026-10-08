# codeviz

Turn a codebase into one self-contained HTML page where you can browse every function as a tree
and click through from a function to the functions it calls (and back to its callers).

```
codeviz ~/src/my-project            # a local directory
codeviz https://github.com/me/repo  # or any git URL (shallow-cloned to a temp dir)
```

Open the generated `<name>-codeviz.html` in a browser. No server, no internet needed.

## What you get

- **Explorer** (left): directories → files → classes/namespaces → functions.
- **Call tree** (middle): everything the selected function calls, expandable as deep as you like.
  Click a name to jump to that function; switch to **Callers** to see the tree in reverse.
  Recursion is marked instead of expanding forever.
- **Source** (right): the function's code with syntax highlighting. Every call that leads to a
  function in the codebase is a link. Hovering a call in the tree highlights where it happens.
- **Search** (`/`), back/forward (`Alt+←/→` or the browser buttons; every view has its own URL),
  light/dark theme, and an overview page listing entry points and the most-called functions.

## Install

Requires Python 3.10+ and git (only for git URLs).

```
pip install git+https://github.com/QuisPic/code-visualizer
# or, from a checkout
pip install -e .
```

Parsing uses [tree-sitter](https://tree-sitter.github.io/) through `tree-sitter-language-pack`,
which downloads each language's grammar the first time it is needed.

## Options

```
codeviz SOURCE [-o OUT.html] [--ref BRANCH] [--name NAME] [-x GLOB ...] [--no-default-excludes] [--json] [--open]
```

| option | |
|---|---|
| `-o, --output` | output file (default `<name>-codeviz.html`) |
| `--ref` | branch or tag to clone for git URLs |
| `-x, --exclude` | skip files/dirs matching a glob, repeatable (`-x tests -x 'docs/*'`) |
| `--no-default-excludes` | also scan `node_modules`, `vendor`, `build`, `dist`, … |
| `--json` | also write the raw call graph next to the HTML |
| `--open` | open the result in your browser |

In a git work tree, files ignored by `.gitignore` are skipped and checked-out submodules are included.

## Languages

C, C++, Python, JavaScript (incl. JSX / ExtendScript `.jsx`), TypeScript/TSX, Go, Rust, Java, Ruby, PHP.

## How calls are linked

There is no type checker involved: a call is matched to function definitions **by name**, then
ranked by how close each candidate is to the caller: `self`/`this` → same class, a matching
qualifier (`ns::f`, `module.f`, `Class::f`), same file, the `.h`/`.cpp` pair, an imported or
included file, same directory, nearest directory. In the page:

- solid links are confident,
- **dashed** links (“guess”) were matched by name only. Untick *guesses* to hide them,
- **amber** links have several equally likely targets and let you pick one,
- calls to things outside the codebase (std library, npm packages, …) are hidden unless you tick *external*.

Calls through function pointers, callbacks, virtual dispatch and dynamic dispatch can't be
resolved statically, so a function reached only that way shows up with no callers.

## Development

```
pip install -e '.[test]'
pytest
```

`codeviz/extract.py` finds functions and call sites, `codeviz/resolve.py` links them,
`codeviz/viewer/` is the page (plain HTML/CSS/JS, inlined into the output by `codeviz/render.py`).

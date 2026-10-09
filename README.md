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
- **Call graph** (middle): the selected function as a node, connected by lines to the functions
  it calls. Click a node to see its code on the right, expand it with **+** to follow its calls as
  deep as you like, double-click it to open that function, drag nodes to rearrange them (a node's subtree moves with it; **Tidy** puts
  them back), drag the background to pan, scroll to zoom. Switch to **Callers** to grow the graph the other
  way, or to **List** for an indented-tree view. Recursion is marked instead of expanding forever. A collapsed node shows how many calls are behind it
  (**+5**); shift-click it to open three levels at once. **?** shows a legend for the colours and line styles.
  way, or to **List** for an indented-tree view. Recursion is marked instead of expanding forever.
- **Impact**: the third tab lists everything that can end up calling the function, grouped by how many
  calls away it is, with a summary ("can affect 58 functions in 21 files, reaching 36 entry points").
  Click a row to see where it makes the call; links that rely on a name-only guess are marked.
- **Source** (right): the function's code with syntax highlighting. Every call that leads to a
  function in the codebase is a link. Hovering a node in the graph highlights where that call happens.
- **Hover cards**: rest the pointer on a call in the source, a graph node or a function in a list to
  see its signature, the comment or docstring above it, where it lives and how many callers and callees
  it has.
- **Path finder** (**⇢ Path** in the top bar, or *find path to…* under a function's name): pick two
  functions and see the shortest chains of calls from one to the other, step by step, with the call
  on each step highlighted in the source.
- **Search** (`/`), back/forward (`Alt+←/→` or the browser buttons; every view has its own URL),
  light/dark theme, and an overview page with a **codebase map** (a treemap of folders and files sized by
  lines, coloured by language or by how much other files call into them; click a folder to zoom in, a file
  to list its functions), entry points, the most-called functions, **call cycles** (groups of mutually
  recursive functions) and **isolated functions** (not called and calling nothing: dead-code candidates).

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

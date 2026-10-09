import json
import re
from pathlib import Path

import pytest

from codeviz.cli import main
from codeviz.project import build

FIXTURE = Path(__file__).parent / "fixtures" / "mixed"


@pytest.fixture(scope="module")
def graph():
    data = build(FIXTURE, "mixed", [], quiet=True)
    funcs = data["funcs"]
    files = data["files"]

    def find(name, path=None):
        hits = [f for f in funcs if f["n"] == name and (path is None or files[f["f"]]["p"] == path)]
        assert len(hits) == 1, f"{name}: {len(hits)} matches"
        return hits[0]

    def targets(caller, callee):
        """Qualified names the calls from `caller` to `callee` were linked to."""
        out = []
        for c in caller["calls"]:
            if c["n"] == callee:
                out += [(funcs[t]["s"] + "." if funcs[t]["s"] else "") + funcs[t]["n"] for t in c.get("t", [])]
        return out

    return data, find, targets


def test_python(graph):
    _, find, targets = graph
    assert targets(find("__init__"), "validate") == ["Greeter.validate"]
    assert targets(find("validate"), "clean") == ["clean"]  # helpers.clean() -> pkg/helpers.py
    assert targets(find("main", "app.py"), "Greeter") == ["Greeter.__init__"]  # class call -> constructor
    assert targets(find("main", "app.py"), "print") == []  # builtin stays external


def test_cpp(graph):
    _, find, targets = graph
    assert find("area")["s"] == "geo::Shape"  # out-of-line Shape::area inside namespace geo
    assert targets(find("scaled"), "area") == ["geo::Shape.area"]  # header calls into the .cpp
    assert targets(find("main", "shapes.cpp"), "total") == ["geo.total"]
    assert targets(find("total"), "push_back") == []  # std:: stays external
    # `old::legacy::load` from inside app::legacy::load must not link to itself
    assert targets(find("load", "codec_new.cpp"), "load") == ["old::legacy.load"]


def test_js(graph):
    _, find, targets = graph
    assert targets(find("increment"), "update") == ["Counter.update"]
    assert targets(find("update"), "render") == ["render"]  # imported from view.js
    assert targets(find("start"), "Counter") == ["Counter.constructor"]  # new Counter()


def test_go_rust_java(graph):
    _, find, targets = graph
    assert targets(find("Start"), "listen") == ["Server.listen"]  # Go receiver var acts as self
    assert targets(find("push"), "push") == []  # self.items.push() is Vec::push, not Stack::push
    assert targets(find("build"), "new") == ["Stack.new"]
    assert targets(find("run"), "helper") == ["App.helper"]


def test_csharp_kotlin_swift_lua(graph):
    _, find, targets = graph
    # C#: this., Class.Static(), new Foo() -> constructor; namespaces stay out of the scope like Java packages
    assert find("Prepare")["s"] == "Invoice"
    assert targets(find("Prepare"), "Recalculate") == ["Invoice.Recalculate"]
    assert targets(find("Recalculate"), "ToCents") == ["Rounding.ToCents"]
    assert targets(find("Create"), "Invoice") == ["Invoice.Invoice"]
    assert targets(find("Prepare"), "WriteLine") == []
    # Kotlin: extension function belongs to its receiver class, object methods, stdlib stays external
    assert targets(find("checkout"), "addItem") == ["Cart.addItem"]
    assert targets(find("addItem"), "recount") == ["Cart.recount"]
    assert targets(find("addItem"), "record") == ["Ledger.record"]
    assert targets(find("addItem"), "add") == []
    # Swift: init is the constructor, extensions share the class scope
    assert targets(find("startPlayer"), "Player") == ["Player.init"]
    assert targets(find("playNext"), "refresh") == ["Player.refresh"]
    assert targets(find("enqueue"), "append") == []
    # Lua: `function T:m()` and `self:m()`, local functions, functions assigned to variables
    assert targets(find("new", "game.lua"), "reset") == ["Board.reset"]
    assert targets(find("new", "game.lua"), "clamp") == ["clamp"]
    assert find("onTick")["k"] == "function"


def test_toplevel_calls(graph):
    _, find, targets = graph
    assert targets(find("(top level)", "ui.js"), "start") == ["start"]


def test_doc_comments(graph):
    _, find, _ = graph
    assert find("format_greeting")["d"] == "Build the greeting text.\n\nThe name is cleaned first."
    assert find("total")["d"] == "Sum of the areas of `n` shapes."
    assert find("start")["d"] == "Create a counter and bump it once."
    assert "d" not in find("main", "shapes.cpp")  # `}` of the namespace above is not a comment
    assert "d" not in find("area")  # #include lines above are not comments in C


def test_cli_writes_self_contained_html(tmp_path):
    out = tmp_path / "out.html"
    assert main([str(FIXTURE), "-o", str(out), "-q", "--json"]) == 0
    html = out.read_text(encoding="utf-8")
    assert "/*__" not in html  # every placeholder was filled
    payload = re.search(r"const DATA = (.*?);</script>", html, re.S).group(1)
    data = json.loads(payload.replace("<\\/", "</"))
    assert data["stats"]["functions"] > 20
    assert json.loads(out.with_suffix(".json").read_text())["name"] == "mixed"


def test_big_pages_carry_gzipped_data(graph):
    import base64
    import gzip

    from codeviz.render import render

    data = graph[0]
    html = render(data, compress=True)
    assert "const DATA = null;" in html
    packed = re.search(r'const DATA_GZ = "([A-Za-z0-9+/=]+)";', html).group(1)
    assert json.loads(gzip.decompress(base64.b64decode(packed))) == data
    assert 'const DATA_GZ = "";' in render(data)  # small pages stay plain


def test_complexity(graph):
    _, find, _ = graph
    assert find("classify")["cx"] == 7  # 1 + if, and, elif, for, if, except
    assert find("label")["cx"] == 2  # nested function: 1 + ternary
    assert "cx" not in find("straight")  # 1 is left out of the data


def test_import_bindings(graph):
    _, find, targets = graph
    assert targets(find("summary"), "clean") == ["clean"]
    summary_clean = [c for c in find("summary")["calls"] if c["n"] == "clean"][0]
    assert summary_clean["x"] == "h"
    # `from other.text import clean` wins over pkg/helpers.clean in the same directory
    data, _, _ = graph
    target = data["funcs"][summary_clean["t"][0]]
    assert data["files"][target["f"]]["p"] == "other/text.py"
    assert targets(find("summary"), "dumps") == []  # `import json` is the standard library
    # `import * as strings` -> util/strings.js, not the local pad()
    pads = [c for c in find("row")["calls"] if c["n"] == "pad"]
    assert [data["files"][data["funcs"][c["t"][0]]["f"]]["p"] for c in pads] == ["util/strings.js", "table.js"]


def test_changed_since(tmp_path):
    import subprocess

    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    (tmp_path / "a.py").write_text("def keep():\n    return 1\n\n\ndef edit():\n    return 2\n")
    git("init", "-q", "-b", "main")
    git("add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base")
    (tmp_path / "a.py").write_text("def keep():\n    return 1\n\n\ndef edit():\n    return 3\n")
    (tmp_path / "b.py").write_text("def fresh():\n    return edit()\n")  # untracked
    data = build(tmp_path, "t", [], quiet=True, changed_since="main")
    ch = {f["n"]: f.get("ch") for f in data["funcs"] if f["k"] != "toplevel"}
    assert ch == {"keep": None, "edit": "m", "fresh": "n"}
    assert data["changed"] == {"ref": "main", "functions": 2}


def test_source_link(tmp_path):
    import subprocess

    from codeviz.project import _web_url, source_link

    assert _web_url("git@github.com:me/repo.git") == ("https://github.com/me/repo", "github")
    assert _web_url("https://user:token@gitlab.com/grp/sub/repo.git") == ("https://gitlab.com/grp/sub/repo", "gitlab")
    assert _web_url("ssh://git@bitbucket.org:22/me/repo") == ("https://bitbucket.org/me/repo", "bitbucket")
    assert _web_url("https://example.com/me/repo.git") is None  # unknown host: no links

    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init", "-q")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("def f():\n    pass\n")
    git("add", ".")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    assert source_link(tmp_path) is None  # no remote
    git("remote", "add", "origin", "git@github.com:me/repo.git")
    sha = subprocess.run(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert source_link(tmp_path / "src") == f"https://github.com/me/repo/blob/{sha}/src/{{path}}#L{{line}}-L{{end}}"
    assert build(tmp_path, "t", [], quiet=True, link="x/{path}")["link"] == "x/{path}"


def test_typed_receivers(graph):
    data, find, _ = graph
    funcs = data["funcs"]

    def linked(caller, line):
        (call,) = [c for c in caller["calls"] if c["l"] == line]
        return [funcs[t]["s"] + "." + funcs[t]["n"] for t in call.get("t", [])], call.get("x")

    drive = find("drive")
    assert linked(drive, drive["l"] + 1) == (["Engine.ignite"], "h")
    assert linked(drive, drive["l"] + 2) == (["Engine.ignite"], "h")
    assert linked(drive, drive["l"] + 4) == (["Engine.ignite"], "h")
    service = find("service")
    assert linked(service, service["l"] + 2) == (["Engine.ignite"], "h")
    ride = find("ride")
    assert linked(ride, ride["l"] + 1) == (["Gear.spin"], "h")
    assert linked(ride, ride["l"] + 2) == (["Wheel.spin"], "h")
    assert linked(ride, ride["l"] + 4) == (["Wheel.spin"], "h")
    fix = find("fix")
    assert linked(fix, fix["l"] + 1) == (["Pump.inflate"], "h")
    assert linked(fix, fix["l"] + 2) == (["Valve.inflate"], "h")


def test_inherited_methods(graph):
    data, find, targets = graph
    assert targets(find("press"), "redraw") == ["Widget.redraw"]
    assert targets(find("boot"), "calibrate") == ["Sensor.calibrate"]
    confidences = {c["x"] for f in (find("press"), find("boot")) for c in f["calls"]}
    assert confidences == {"h"}


def test_churn(tmp_path):
    import subprocess

    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                       check=True, capture_output=True)

    git("init", "-q")
    (tmp_path / "a.py").write_text("def f():\n    pass\n")
    (tmp_path / "b.py").write_text("def g():\n    pass\n")
    git("add", ".")
    git("commit", "-qm", "one")
    (tmp_path / "a.py").write_text("def f():\n    return 1\n")
    git("commit", "-qam", "two")
    data = build(tmp_path, "t", [], quiet=True, churn_since="1 year")
    assert {f["p"]: f.get("cc") for f in data["files"]} == {"a.py": 2, "b.py": 1}
    assert data["churn"] == {"since": "1 year", "commits": 2}
    assert "churn" not in build(tmp_path, "t", [], quiet=True)


def test_callbacks(graph):
    data, find, targets = graph
    refs = lambda f: {c["n"]: targets(f, c["n"]) for c in f["calls"] if c.get("r")}
    assert refs(find("schedule")) == {"onTick": ["onTick"]}  # `finished` is a local variable there
    assert refs(find("spawn")) == {"crunch": ["crunch"]}
    assert [c["n"] for c in find("onTick")["calls"]] == []

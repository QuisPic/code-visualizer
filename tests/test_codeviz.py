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

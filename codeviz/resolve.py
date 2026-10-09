"""Link each call site to the function definition(s) it most likely refers to.

Resolution is name based, helped by declared types (`Foo f`, `f: Foo`, `f = new Foo()`) of locals,
parameters and members when a call's receiver is one of those, and ranked by how close the candidate is to the
caller: same class, matching qualifier, same file, header/source pair, included/imported
file, same directory.
"""

from __future__ import annotations

import posixpath
import re
from collections import defaultdict
from dataclasses import replace
from typing import NamedTuple
from pathlib import PurePosixPath

from .extract import Call, FileInfo, Function

MAX_TARGETS = 8
_TEST_DIRS = {"test", "tests", "spec", "specs", "__tests__", "testing", "unit-tests"}
_STRONG = 50
_JS_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")


def _is_test(path: PurePosixPath) -> bool:
    return any(p.lower() in _TEST_DIRS for p in path.parts[:-1])


class _PathInfo(NamedTuple):
    stem: str
    parent: str
    parent_name: str
    parent_parts: tuple[str, ...]
    is_test: bool


def _path_info(path: str) -> _PathInfo:
    p = PurePosixPath(path)
    return _PathInfo(p.stem, str(p.parent), p.parent.name, p.parent.parts, _is_test(p))


class Resolver:
    def __init__(self, files: list[FileInfo]):
        self.files = {f.path: f for f in files}
        self.functions: list[Function] = [fn for f in files for fn in f.functions]
        self.by_name: dict[str, list[int]] = defaultdict(list)
        self.ctors: dict[str, list[int]] = defaultdict(list)  # class name -> constructor ids
        for i, fn in enumerate(self.functions):
            if fn.kind == "toplevel":
                continue
            self.by_name[fn.name].append(i)
            if fn.kind == "constructor" and fn.scope:
                self.ctors[fn.scope[-1]].append(i)
        # path facts are compared for every candidate of every call, so work them out once
        self.paths = {path: _path_info(path) for path in self.files}
        self._cache: dict[tuple, tuple[list[int], str]] = {}
        self.class_files: dict[str, set[str]] = defaultdict(set)  # class name -> files defining its methods
        for fn in self.functions:
            if fn.scope and fn.kind != "toplevel":
                self.class_files[fn.scope[-1]].add(fn.path)
        self.field_types: dict[str, dict[str, str]] = defaultdict(dict)
        for f in files:
            for key, fields in f.field_types.items():
                for name, typ in fields.items():
                    prev = self.field_types[key].get(name)
                    self.field_types[key][name] = typ if prev in (None, typ) else ""

        self._quals: dict[tuple, tuple[bool, bool, list[str], str]] = {}
        # for import bindings: top-level functions and constructors by (file, name)
        self.in_file: dict[tuple[str, str], list[int]] = defaultdict(list)
        for i, fn in enumerate(self.functions):
            if fn.kind == "constructor" and len(fn.scope) == 1:
                self.in_file[(fn.path, fn.scope[0])].append(i)
            elif fn.kind != "toplevel" and not fn.scope:
                self.in_file[(fn.path, fn.name)].append(i)
        self.py_modules: dict[str, list[str]] = defaultdict(list)  # "a/b" -> [".../a/b.py", ".../a/b/__init__.py"]
        for path, f in self.files.items():
            if f.lang.family == "python":
                stem = path[:-3] if path.endswith(".py") else path.rsplit(".", 1)[0]
                stem = stem[:-len("/__init__")] if stem.endswith("/__init__") else stem
                parts = stem.split("/")
                for k in range(1, len(parts) + 1):
                    self.py_modules["/".join(parts[-k:])].append(path)
        self._module_cache: dict[tuple[str, str], str | None] = {}

    def _qualifier(self, q: str | None, caller: Function) -> tuple[bool, bool, list[str], str]:
        """(self call, self member, qualifier parts, receiver name) for a call's qualifier, cached."""
        key = (q, caller.lang.name, caller.receiver)
        hit = self._quals.get(key)
        if hit is not None:
            return hit
        self_call = q is not None and (q in caller.lang.self_names or q in ("this", "super", "parent")
                                       or q == caller.receiver)
        self_member = q is not None and not self_call and any(
            q.startswith(s + sep) for s in caller.lang.self_names | {"this"} for sep in (".", "->"))
        q_parts = [p for p in (q or "").replace("->", ".").replace("::", ".").split(".") if p]
        last = q_parts[-1] if q_parts else ""
        receiver = last.lower().removeprefix("m_").removeprefix("_").replace("_", "")
        hit = self._quals[key] = (self_call, self_member, q_parts, receiver)
        return hit

    # ---- imports ---------------------------------------------------------------------------
    def module_file(self, importer: str, spec: str) -> str | None:
        """The file in the project that an import spec in `importer` refers to, if any."""
        key = (importer, spec)
        if key not in self._module_cache:
            self._module_cache[key] = self._find_module(importer, spec)
        return self._module_cache[key]

    def _find_module(self, importer: str, spec: str) -> str | None:
        family = self.files[importer].lang.family
        here = posixpath.dirname(importer)
        if family == "js":
            if not spec.startswith("."):
                return None  # a package
            base = posixpath.normpath(posixpath.join(here, spec))
            stem, ext = posixpath.splitext(base)
            tries = [base] if ext else []
            # TS sources import "./x.js" for x.ts
            stems = [stem, base] if ext in (".js", ".mjs", ".cjs", ".jsx") else [base]
            tries += [s + e for s in stems for e in _JS_EXTS] + [base + "/index" + e for e in _JS_EXTS]
            return next((t for t in tries if t in self.files), None)
        if family == "python":
            dots = len(spec) - len(spec.lstrip("."))
            rest = spec[dots:].replace(".", "/")
            if dots:
                base = here
                for _ in range(dots - 1):
                    base = posixpath.dirname(base)
                rel = posixpath.normpath(posixpath.join(base, rest)) if rest else base
                tries = [rel + ".py", rel + "/__init__.py"]
                return next((t for t in tries if t in self.files), None)
            # an absolute import names a top-level package: `import json` inside flask/json/ is the
            # standard library, not flask.json, so the match must not sit inside another package
            def top_level(h: str) -> bool:
                root = h[:-3].removesuffix("/__init__")[:-len(rest)].rstrip("/")
                return (root + "/__init__.py" if root else "__init__.py") not in self.files
            hits = [h for h in self.py_modules.get(rest, []) if top_level(h)]
            if len(hits) > 1:  # several packages with that module: take the one nearest the importer
                def shared(h: str) -> int:
                    return len(posixpath.commonpath([here, posixpath.dirname(h)]) if here else "")
                hits.sort(key=shared, reverse=True)
                if shared(hits[0]) == shared(hits[1]):
                    return None
            return hits[0] if hits else None
        return None

    def _defined(self, path: str, name: str, depth: int = 0) -> list[int] | None:
        """Functions named `name` at the top of `path`, following re-exports (`from .app import Flask`)."""
        ids = self.in_file.get((path, name))
        if ids:
            return ids
        bound = self.files[path].bindings.get(name)
        if bound is None or bound[1] is None or depth >= 3:
            return None
        nxt = self.module_file(path, bound[0])
        return self._defined(nxt, bound[1], depth + 1) if nxt else None

    def _bound(self, caller: Function, call: Call) -> list[int] | None:
        """Targets of a call to an imported name or through an imported module, when the import
        settles it. [] means external (a Python module that isn't in the project), None means unknown."""
        info = self.files[caller.path]
        if not info.bindings:
            return None
        python = caller.lang.family == "python"
        if call.qualifier is None:
            bound = info.bindings.get(call.name)
            if bound is None or bound[1] is None:
                return None
            path = self.module_file(caller.path, bound[0])
            if path:
                return self._defined(path, bound[1])
            # `from library import f`: a Python name imported from outside the project
            return [] if python and not bound[0].startswith(".") else None
        parts = call.qualifier.split(".")
        bound = info.bindings.get(parts[0])
        if bound is None or call.sep != "." or not all(parts):
            return None
        base, name = bound
        if not python:
            return None if name is not None or len(parts) > 1 else self._in_module(caller, base, call.name)
        # `from pkg import mod; mod.f()` / `import a.b; a.b.f()`
        spec = base
        for extra in ([name] if name else []) + parts[1:]:
            spec = spec + ("" if spec.endswith(".") else ".") + extra
        path = self.module_file(caller.path, spec)
        if path:
            return self._defined(path, call.name)
        if name is None and self.module_file(caller.path, base) is None:
            return []  # `import x` of a library: everything reached through it is outside the project
        return None  # an attribute of something in the project (`flask.current_app.json.dump()`)

    def _in_module(self, caller: Function, spec: str, name: str) -> list[int] | None:
        path = self.module_file(caller.path, spec)
        return self._defined(path, name) if path else None

    def _receiver_type(self, caller: Function, q: str) -> str | None:
        """Class of a call's receiver when it is a typed local, parameter or member (`f`, `self.f`, `this->f`)."""
        m = re.fullmatch(r"(?:self|this)(?:\.|->)([A-Za-z_]\w*)", q)
        if m:
            typ = self.field_types.get(".".join(caller.scope), {}).get(m.group(1))
        elif re.fullmatch(r"[A-Za-z_$][\w$]*", q):
            typ = caller.var_types.get(q)
            if typ is None and caller.lang.family in ("c", "java"):  # implicit this: `m_foo->bar()`
                typ = self.field_types.get(".".join(caller.scope), {}).get(q)
        else:
            return None
        if not typ or typ not in self.class_files:
            return None
        # only trust it when the class is visible from the caller (same file/dir, or imported), so a
        # same-named class elsewhere isn't linked with confidence
        here = PurePosixPath(caller.path)
        imports = self.files[caller.path].imports
        for path in self.class_files[typ]:
            p = PurePosixPath(path)
            if p.parent == here.parent or p.stem in imports or p.parent.name in imports:
                return typ
        return None

    def _score(self, call: Call, caller: Function, cand: Function) -> int | None:
        if cand.lang.family != caller.lang.family:
            return None
        score = 0
        caller_cls = caller.scope[-1] if caller.scope else None
        cand_cls = cand.scope[-1] if cand.scope else None
        q = call.qualifier
        self_call, self_member, q_parts, receiver = self._qualifier(q, caller)
        last = q_parts[-1] if q_parts else ""

        if self_member and caller_cls and cand_cls == caller_cls:
            return None  # `self.items.push()` calls a method of the field, not of our own class
        if self_call:
            score += 100 if caller_cls and cand_cls == caller_cls else (-10 if cand_cls else -40)
        elif q:
            cand_info = self.paths[cand.path]
            if cand.scope and last in cand.scope:
                score += 80
                # compare the rest of the qualifier with the scope around that name, right to left:
                # `a::legacy::f` fully matches scope [x, a, legacy] but contradicts [x, b, legacy]
                end = len(cand.scope) - 1 - cand.scope[::-1].index(last)
                outer_q, outer_s = q_parts[:-1][::-1], cand.scope[:end][::-1]
                if outer_q and all(a == b for a, b in zip(outer_q, outer_s)) and len(outer_s) >= len(outer_q):
                    score += 40
                elif any(a != b for a, b in zip(outer_q, outer_s)):
                    score -= 40
                if end != len(cand.scope) - 1:
                    score -= 30  # the candidate sits in a nested scope the call doesn't name
            elif last and last in (cand_info.stem, cand_info.parent_name):
                score += 60  # module.func() / package.Func()
            elif call.sep == "::":
                return None  # qualified by a namespace/class we don't have (std::, a library, ...)
            elif call.sep in (".", "->") and not cand.scope and cand.lang.family in ("c", "java", "rust"):
                return None  # obj.method() can't be a free function in these languages
            elif cand_cls and len(receiver) > 2 and (receiver in cand_cls.lower() or cand_cls.lower() in receiver):
                score += 40  # `picker.render()` -> ObjectPicker::render
        else:
            if caller.scope and cand.scope == caller.scope:
                score += 50
            elif not cand.scope or cand_cls is None:
                score += 10
            elif caller.lang.family in ("python", "js", "go") and cand.kind in ("method", "constructor"):
                score -= 20  # a bare call in these languages rarely hits a method

        caller_path, cand_path = self.paths[caller.path], self.paths[cand.path]
        if cand.path == caller.path:
            score += 30
        elif cand_path.stem == caller_path.stem and cand_path.parent == caller_path.parent:
            score += 25  # foo.h / foo.cpp
        imports = self.files[caller.path].imports
        if cand_path.stem in imports or cand_path.parent_name in imports:
            score += 20
        if cand_path.parent == caller_path.parent:
            score += 10
        else:
            # nearer in the directory tree wins ties between same-named copies
            shared = 0
            for a, b in zip(caller_path.parent_parts, cand_path.parent_parts):
                if a != b:
                    break
                shared += 1
            score += min(shared, 3) * 2
        if not caller_path.is_test and cand_path.is_test:
            score -= 1  # prefer the library copy over a test's private copy
        return score

    def resolve(self, caller: Function, call: Call) -> tuple[list[int], str]:
        """Return (target function ids, confidence) where confidence is high | low | ambiguous."""
        # a typed receiver changes the answer, so swap it in before the cache lookup
        if call.qualifier and call.sep in (".", "->"):
            typ = self._receiver_type(caller, call.qualifier)
            # skip it when the method isn't on that class (probably inherited: keep the name-based guess)
            if typ and any(self.functions[i].scope and self.functions[i].scope[-1] == typ
                           for i in self.by_name.get(call.name, ())):
                call = replace(call, qualifier=typ)  # `s.area()` with `Shape s` -> `Shape.area()`
        # the answer only depends on these, and the same call repeats a lot within a file
        key = (caller.path, tuple(caller.scope), caller.receiver, call.name, call.qualifier, call.sep, call.ctor)
        hit = self._cache.get(key)
        if hit is None:
            hit = self._cache[key] = self._resolve(caller, call)
        return list(hit[0]), hit[1]

    def _resolve(self, caller: Function, call: Call) -> tuple[list[int], str]:
        bound = self._bound(caller, call)
        if bound is not None:
            if not bound:
                return [], "none"
            return bound[:MAX_TARGETS], "high" if len(bound) == 1 else "ambiguous"
        candidates = list(self.by_name.get(call.name, ()))
        if call.ctor or not candidates:
            # `new Foo()` / `Foo()` with no function named Foo -> Foo's constructor(s)
            candidates = candidates + [i for i in self.ctors.get(call.name, ()) if i not in candidates]
        scored = []
        for i in candidates:
            s = self._score(call, caller, self.functions[i])
            if s is not None:
                scored.append((s, i))
        if not scored:
            return [], "none"
        best = max(s for s, _ in scored)
        top = [i for s, i in scored if s == best][:MAX_TARGETS]
        if len(top) > 1:
            return top, "ambiguous"
        unique_name = len(scored) == 1
        return top, "high" if best >= _STRONG or (unique_name and call.sep is None) else "low"

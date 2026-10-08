"""Link each call site to the function definition(s) it most likely refers to.

Resolution is name based (no type inference), ranked by how close the candidate is to the
caller: same class, matching qualifier, same file, header/source pair, included/imported
file, same directory.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import PurePosixPath

from .extract import Call, FileInfo, Function

MAX_TARGETS = 8
_TEST_DIRS = {"test", "tests", "spec", "specs", "__tests__", "testing", "unit-tests"}
_STRONG = 50


def _is_test(path: PurePosixPath) -> bool:
    return any(p.lower() in _TEST_DIRS for p in path.parts[:-1])


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

    def _score(self, call: Call, caller: Function, cand: Function) -> int | None:
        if cand.lang.family != caller.lang.family:
            return None
        score = 0
        caller_cls = caller.scope[-1] if caller.scope else None
        cand_cls = cand.scope[-1] if cand.scope else None
        q = call.qualifier
        self_call = q is not None and (q in caller.lang.self_names or q in ("this", "super", "parent")
                                       or q == caller.receiver)
        self_member = q is not None and not self_call and any(
            q.startswith(s + sep) for s in caller.lang.self_names | {"this"} for sep in (".", "->"))

        if self_member and caller_cls and cand_cls == caller_cls:
            return None  # `self.items.push()` calls a method of the field, not of our own class
        if self_call:
            score += 100 if caller_cls and cand_cls == caller_cls else (-10 if cand_cls else -40)
        elif q:
            q_parts = [p for p in q.replace("->", ".").replace("::", ".").split(".") if p]
            last = q_parts[-1] if q_parts else ""
            cand_path = PurePosixPath(cand.path)
            receiver = last.lower().removeprefix("m_").removeprefix("_").replace("_", "")
            if cand.scope and last in cand.scope:
                score += 80
            elif last and last in (cand_path.stem, cand_path.parent.name):
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

        caller_path, cand_path = PurePosixPath(caller.path), PurePosixPath(cand.path)
        if cand.path == caller.path:
            score += 30
        elif cand_path.stem == caller_path.stem and cand_path.parent == caller_path.parent:
            score += 25  # foo.h / foo.cpp
        imports = self.files[caller.path].imports
        if cand_path.stem in imports or cand_path.parent.name in imports:
            score += 20
        if cand_path.parent == caller_path.parent:
            score += 10
        else:
            # nearer in the directory tree wins ties between same-named copies
            shared = 0
            for a, b in zip(caller_path.parent.parts, cand_path.parent.parts):
                if a != b:
                    break
                shared += 1
            score += min(shared, 3) * 2
        if not _is_test(caller_path) and _is_test(cand_path):
            score -= 1  # prefer the library copy over a test's private copy
        return score

    def resolve(self, caller: Function, call: Call) -> tuple[list[int], str]:
        """Return (target function ids, confidence) where confidence is high | low | ambiguous."""
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

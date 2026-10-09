"""Walk source files with tree-sitter and pull out functions and the calls they make."""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass, field
from pathlib import Path

from tree_sitter import Node

from .languages import Language

_TEMPLATE_ARGS = re.compile(r"<[^<>]*>")
_IDENT = re.compile(r"[A-Za-z_$][\w$]*")


@dataclass
class Call:
    name: str
    qualifier: str | None  # receiver / scope text, e.g. "self", "obj", "ns::Foo"
    sep: str | None  # ".", "->", "::" or None for a plain call
    line: int  # 1-based
    col: int  # 0-based character column of the name
    ctor: bool = False  # `new Foo()` style call


@dataclass
class Function:
    name: str
    scope: list[str]  # enclosing namespaces / classes, outermost first
    path: str  # file path relative to the project root
    lang: Language
    start: int  # 1-based first line
    end: int  # 1-based last line
    code: str
    kind: str = "function"  # function | method | constructor | toplevel
    calls: list[Call] = field(default_factory=list)
    receiver: str | None = None  # Go receiver variable, e.g. `s` in `func (s *Server) Start()`
    doc: str = ""  # comment right above the definition, or a Python docstring


@dataclass
class FileInfo:
    path: str
    lang: Language
    lines: int
    imports: set[str]  # file stems / module names this file imports or includes
    functions: list[Function]
    classes: list[tuple[list[str], str]]  # (scope, class name) for constructor resolution


def _text(node: Node | None) -> str:
    return node.text.decode("utf-8", "replace") if node is not None else ""


_DOC_MAX_LINES = 8
_DOC_MAX_CHARS = 500
_COMMENT_MARK = re.compile(r"^\s*(?:/\*+!?|\*+/|\*+(?!/)|//+!?|#+|--)\s?")


def _clean_doc(lines: list[str]) -> str:
    """Strip comment markers and blank edges; keep the first few lines."""
    out = []
    for line in lines:
        line = _COMMENT_MARK.sub("", line.rstrip())
        line = re.sub(r"\s*\*+/\s*$", "", line).rstrip()
        out.append(line)
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    # drop the common indent left after removing the markers
    indent = min((len(l) - len(l.lstrip()) for l in out if l.strip()), default=0)
    text = "\n".join(l[indent:] for l in out[:_DOC_MAX_LINES])
    if len(out) > _DOC_MAX_LINES or len(text) > _DOC_MAX_CHARS:
        text = text[:_DOC_MAX_CHARS].rstrip() + " …"
    return text


def _split_qualified(text: str) -> list[str]:
    """`ns::Foo<T>::get` -> ["ns", "Foo", "get"]."""
    prev = None
    while prev != text:
        prev, text = text, _TEMPLATE_ARGS.sub("", text)
    return [p.strip() for p in re.split(r"::|\\", text) if p.strip()]


class _Extractor:
    def __init__(self, lang: Language, path: str, source: bytes):
        self.lang = lang
        self.path = path
        self.source = source
        self.lines = source.split(b"\n")
        self.functions: list[Function] = []
        self.classes: list[tuple[list[str], str]] = []
        self.toplevel: Function | None = None

    # ---- helpers -------------------------------------------------------------------------
    def _col(self, node: Node) -> int:
        row, byte_col = node.start_point
        return len(self.lines[row][:byte_col].decode("utf-8", "replace")) if row < len(self.lines) else byte_col

    def _code(self, start_row: int, end_row: int) -> str:
        return b"\n".join(self.lines[start_row:end_row + 1]).decode("utf-8", "replace")

    def _leading_comment(self, row: int) -> str:
        """The comment block that ends on the line right above `row` (0-based), if any."""
        hash_comments = self.lang.family not in ("c",)  # `#include` / `#define` aren't comments in C
        lines: list[str] = []
        in_block = False
        r = row - 1
        while r >= 0 and len(lines) < 40:
            text = self.lines[r].decode("utf-8", "replace").strip()
            if in_block:
                lines.append(text)
                if text.startswith("/*"):
                    in_block = False
            elif text.endswith("*/"):
                lines.append(text)
                in_block = not text.startswith("/*")
            elif text.startswith(("//", "--")) or (hash_comments and text.startswith("#") and not text.startswith("#!")):
                lines.append(text)
            elif text.startswith("@") and not lines:  # decorators / annotations sit between comment and def
                pass
            else:
                break
            r -= 1
        return _clean_doc(lines[::-1]) if lines and not in_block else ""

    def _docstring(self, node: Node) -> str:
        body = node.child_by_field_name("body")
        first = body.named_children[0] if body is not None and body.named_children else None
        if first is not None and first.type == "expression_statement":  # older grammars wrap the string
            first = first.named_children[0] if first.named_children else None
        if first is None or first.type != "string":
            return ""
        text = _text(first)
        text = re.sub(r'^[rRbBuUfF]*("""|\'\'\'|"|\')', "", text)
        text = re.sub(r'("""|\'\'\'|"|\')$', "", text)
        return _clean_doc(inspect.cleandoc(text).split("\n"))

    # ---- function naming -----------------------------------------------------------------
    def _c_declarator_name(self, node: Node | None) -> list[str] | None:
        while node is not None:
            t = node.type
            if t in ("identifier", "field_identifier", "destructor_name", "operator_name", "operator_cast"):
                return [_text(node)]
            if t in ("qualified_identifier", "template_function", "scoped_identifier"):
                parts = _split_qualified(_text(node))
                return parts or None
            nxt = node.child_by_field_name("declarator")
            if nxt is None:
                named = [c for c in node.named_children if c.type not in ("parameter_list", "type_qualifier")]
                nxt = named[-1] if named else None
            node = nxt
        return None

    def _assigned_name(self, node: Node) -> list[str] | None:
        """Name for an anonymous JS function from the thing it is assigned to."""
        parent = node.parent
        while parent is not None and parent.type == "parenthesized_expression":
            parent = parent.parent
        if parent is None:
            return None
        t = parent.type
        if t == "variable_declarator":
            return [_text(parent.child_by_field_name("name"))]
        if t in ("pair", "property_assignment"):
            key = _text(parent.child_by_field_name("key")).strip("'\"")
            return [key] if _IDENT.fullmatch(key) else None
        if t in ("public_field_definition", "field_definition"):
            return [_text(parent.child_by_field_name("name") or parent.child_by_field_name("property"))]
        if t == "assignment_expression":
            left = parent.child_by_field_name("left")
            parts = [p for p in _text(left).split(".") if p and p != "prototype"]
            if parts and all(_IDENT.fullmatch(p) for p in parts):
                return parts[-2:] if parts[0] not in ("this", "exports", "module") else parts[-1:]
        return None

    def _function_name(self, node: Node) -> list[str] | None:
        t = node.type
        if self.lang.family == "c":
            return self._c_declarator_name(node.child_by_field_name("declarator"))
        if t in ("arrow_function", "function_expression", "function", "generator_function"):
            assigned = self._assigned_name(node)
            if assigned:
                return assigned
            name = node.child_by_field_name("name")
            return [_text(name)] if name is not None else None
        name = node.child_by_field_name("name")
        if name is None:
            return None
        parts = [_text(name)]
        if t == "method_declaration" and self.lang.name == "go":
            recv = _text(node.child_by_field_name("receiver"))
            idents = _IDENT.findall(_TEMPLATE_ARGS.sub("", recv.replace("[", "<").replace("]", ">")))
            if idents:
                parts.insert(0, idents[-1])
        return parts

    def _go_receiver(self, node: Node) -> str | None:
        idents = _IDENT.findall(_text(node.child_by_field_name("receiver")))
        return idents[0] if len(idents) >= 2 else None

    # ---- calls ---------------------------------------------------------------------------
    def _callee(self, node: Node) -> tuple[Node, str | None, str | None] | None:
        """Return (name node, qualifier, separator) for a callee expression."""
        t = node.type
        if t in ("identifier", "field_identifier", "property_identifier", "type_identifier", "name",
                 "constant", "private_property_identifier"):
            return node, None, None
        if t in ("member_expression", "attribute", "field_expression", "selector_expression"):
            obj = (node.child_by_field_name("object") or node.child_by_field_name("argument")
                   or node.child_by_field_name("value") or node.child_by_field_name("operand"))
            prop = (node.child_by_field_name("property") or node.child_by_field_name("attribute")
                    or node.child_by_field_name("field"))
            if prop is None:
                return None
            op = _text(node.child_by_field_name("operator")) or ("->" if b"->" in node.text else ".")
            return prop, _text(obj), op
        if t in ("qualified_identifier", "scoped_identifier"):
            inner = node.child_by_field_name("name")
            scope = node.child_by_field_name("scope") or node.child_by_field_name("path")
            if inner is None:
                return None
            res = self._callee(inner)
            if res is None:
                return None
            name_node, q, _ = res
            qual = "::".join(_split_qualified(_text(scope)) + ([q] if q else []))
            return name_node, qual or None, "::"
        if t in ("template_function", "generic_function"):
            inner = node.child_by_field_name("name") or node.child_by_field_name("function")
            return self._callee(inner) if inner is not None else None
        if t in ("parenthesized_expression", "non_null_expression"):
            named = node.named_children
            return self._callee(named[0]) if named else None
        return None

    def _call(self, node: Node) -> Call | None:
        t = node.type
        if t in self.lang.constructor_calls:
            target = node.child_by_field_name("constructor") or node.child_by_field_name("type")
            if target is None:
                named = [c for c in node.named_children if c.type not in ("arguments", "argument_list")]
                target = named[0] if named else None
            if target is None:
                return None
            res = self._callee(target)
            if res is None:
                parts = _split_qualified(_text(target))
                if not parts or not _IDENT.fullmatch(parts[-1]):
                    return None
                return Call(parts[-1], "::".join(parts[:-1]) or None, None,
                            target.start_point[0] + 1, self._col(target), ctor=True)
            name_node, q, sep = res
            return Call(_text(name_node), q, sep, name_node.start_point[0] + 1, self._col(name_node), ctor=True)

        # languages where the call node itself carries name/receiver fields
        if self.lang.name in ("java", "ruby") or t in ("member_call_expression", "scoped_call_expression",
                                                        "nullsafe_member_call_expression"):
            name = node.child_by_field_name("name") or node.child_by_field_name("method")
            if name is None:
                return None
            recv = (node.child_by_field_name("object") or node.child_by_field_name("receiver")
                    or node.child_by_field_name("scope"))
            sep = "::" if t == "scoped_call_expression" else ("." if recv is not None else None)
            return Call(_text(name), _text(recv) if recv is not None else None, sep,
                        name.start_point[0] + 1, self._col(name))

        fn = node.child_by_field_name("function")
        if fn is None:
            return None
        res = self._callee(fn)
        if res is None:
            return None
        name_node, q, sep = res
        name = _text(name_node)
        if not name or not _IDENT.fullmatch(name.lstrip("~")):
            return None
        return Call(name, q, sep, name_node.start_point[0] + 1, self._col(name_node))

    # ---- traversal -----------------------------------------------------------------------
    def _new_function(self, node: Node, parts: list[str], scope: list[str], in_class: bool) -> Function:
        full_scope = scope + parts[:-1]
        name = parts[-1]
        kind = "method" if in_class or len(parts) > 1 else "function"
        cls = full_scope[-1] if full_scope else None
        if name in self.lang.constructor_names or (cls is not None and name == cls):
            kind = "constructor"
        if self.lang.name == "java" and node.type == "constructor_declaration":
            kind = "constructor"
        # include a leading template<...> line for C++
        start_node = node.parent if node.parent is not None and node.parent.type == "template_declaration" else node
        start, end = start_node.start_point[0], node.end_point[0]
        doc = self._docstring(node) if self.lang.name == "python" else ""
        doc = doc or self._leading_comment(start)
        return Function(name, full_scope, self.path, self.lang, start + 1, end + 1, self._code(start, end), kind,
                        doc=doc)

    def run(self, root: Node) -> None:
        # iterative DFS: (node, scope, current function, inside-a-class flag)
        stack: list[tuple[Node, list[str], Function | None, bool]] = [(root, [], None, False)]
        lang = self.lang
        while stack:
            node, scope, func, in_class = stack.pop()
            t = node.type
            child_scope, child_func, child_in_class = scope, func, in_class

            if t in lang.scopes:
                field_name = lang.scopes[t]
                name_node = node.child_by_field_name(field_name) if field_name else None
                name = _split_qualified(_text(name_node)) if name_node is not None else []
                if name:
                    child_scope = scope + name
                    if t not in ("namespace_definition", "mod_item", "module", "internal_module"):
                        child_in_class = True
                        self.classes.append((scope, name[-1]))
                    else:
                        child_in_class = False
            elif t in lang.functions and not (lang.family == "c" and node.child_by_field_name("body") is None):
                parts = self._function_name(node)
                if parts and all(parts):
                    child_func = self._new_function(node, parts, scope, in_class)
                    if t == "method_declaration" and lang.name == "go":
                        child_func.receiver = self._go_receiver(node)
                    self.functions.append(child_func)
                    child_scope, child_in_class = scope + parts[:-1], False
            elif t in lang.calls or t in lang.constructor_calls:
                call = self._call(node)
                if call is not None:
                    owner = func or self._toplevel()
                    owner.calls.append(call)

            for child in reversed(node.children):
                if child.is_named:
                    stack.append((child, child_scope, child_func, child_in_class))

    def _toplevel(self) -> Function:
        if self.toplevel is None:
            self.toplevel = Function("(top level)", [], self.path, self.lang, 1, len(self.lines),
                                     "", "toplevel")
        return self.toplevel


_INCLUDE = re.compile(
    rb"""^\s*(?:\#\s*include\s*[<"]([^>"]+)[>"]"""
    rb"""|import\s+(?:[\w*{}\s,$]+\s+from\s+)?['"]([^'"]+)['"]"""
    rb"""|from\s+([\w.]+)\s+import"""
    rb"""|import\s+([\w.]+)"""
    rb"""|.*require(?:_once)?\s*\(?\s*['"]([^'"]+)['"]"""
    rb"""|\#include\s+['"]([^'"]+)['"]"""
    rb"""|//\s*@include\s+['"]([^'"]+)['"]"""
    rb"""|use\s+([\w:]+))""",
    re.MULTILINE,
)


def _imports(source: bytes) -> set[str]:
    stems: set[str] = set()
    for m in _INCLUDE.finditer(source):
        target = next((g for g in m.groups() if g), None)
        if not target:
            continue
        target = target.decode("utf-8", "replace")
        for piece in re.split(r"[/.:\\]+", target):
            if piece:
                stems.add(piece)
        stem = Path(target).stem
        if stem:
            stems.add(stem)
    return stems


def extract_file(lang: Language, parser, rel_path: str, source: bytes) -> FileInfo:
    tree = parser.parse(source)
    ex = _Extractor(lang, rel_path, source)
    ex.run(tree.root_node)
    functions = ex.functions
    if ex.toplevel is not None:
        ex.toplevel.code = ""  # top-level code is shown via its call list only
        functions = [ex.toplevel] + functions
    return FileInfo(rel_path, lang, source.count(b"\n") + 1, _imports(source), functions, ex.classes)

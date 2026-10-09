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
# grammars without field names (Kotlin) put the name in the first identifier-like child
_NAME_TYPES = ("simple_identifier", "type_identifier", "identifier")
# declarations whose name is a keyword rather than an identifier
_FIXED_NAMES = {"init_declaration": "init", "deinit_declaration": "deinit", "secondary_constructor": "constructor"}

# decision points for cyclomatic complexity, across all supported grammars
_BRANCHES = frozenset({
    "if_statement", "if_expression", "if", "elif_clause", "else_if_clause", "elsif", "elseif_statement",
    "if_modifier", "unless", "unless_modifier", "if_clause", "guard_statement",
    "for_statement", "for_in_statement", "for_range_loop", "enhanced_for_statement", "foreach_statement",
    "for_expression", "for", "while_statement", "while_expression", "while", "while_modifier", "until",
    "until_modifier", "do_statement", "loop_expression", "repeat_statement",
    "case_statement", "switch_case", "switch_label", "switch_section", "case_clause", "expression_case",
    "type_case", "communication_case", "match_arm", "when", "when_entry", "switch_entry",
    "catch_clause", "except_clause", "rescue", "rescue_modifier", "catch_block",
    "conditional_expression", "ternary_expression", "conditional", "boolean_operator",
    "conjunction_expression", "disjunction_expression",
})
_DEFAULT_CASE = re.compile(rb"\s*(default|else)\b")
_LOGICAL = frozenset({"&&", "||", "and", "or"})


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
    complexity: int = 1  # cyclomatic: 1 + branches, loops, cases, catches and && / ||
    var_types: dict[str, str] = field(default_factory=dict)  # local/parameter name -> declared class name


@dataclass
class FileInfo:
    path: str
    lang: Language
    lines: int
    imports: set[str]  # file stems / module names this file imports or includes
    functions: list[Function]
    classes: list[tuple[list[str], str]]  # (scope, class name) for constructor resolution
    # local name -> (module spec, imported name or None for the module itself), e.g.
    # `from .util import clean as c` -> {"c": (".util", "clean")}, `import * as ns from "./x"` -> {"ns": ("./x", None)}
    bindings: dict[str, tuple[str, str | None]] = field(default_factory=dict)
    field_types: dict[str, dict[str, str]] = field(default_factory=dict)  # "ns.Class" -> member name -> class name


# Declarations that give a variable, parameter or member a type (or a value whose type is obvious).
_DECLS = {
    "declaration", "parameter_declaration", "optional_parameter_declaration", "field_declaration",
    "variable_declarator", "formal_parameter", "required_parameter", "optional_parameter",
    "typed_parameter", "typed_default_parameter", "assignment", "assignment_expression",
    "short_var_declaration", "var_spec", "parameter", "let_declaration", "public_field_definition",
}
_WRAPPERS = {"unique_ptr", "shared_ptr", "weak_ptr", "optional", "Box", "Rc", "Arc", "RefCell", "Option",
             "Optional", "Ref", "Ptr", "QPointer", "QSharedPointer", "make_unique", "make_shared"}
_FACTORIES = {"new", "create", "make", "default", "from", "getInstance", "instance", "shared"}
_TYPE_NOISE = re.compile(r"\b(?:const|volatile|mut|struct|class|typename|final|readonly|dyn|impl)\b|[&*?^]|\[\]")


def _first_arg(args: str) -> str:
    depth = 0
    for i, ch in enumerate(args):
        if ch in "<[(":
            depth += 1
        elif ch in ">])":
            depth -= 1
        elif ch == "," and depth == 0:
            return args[:i]
    return args


def _type_name(text: str) -> str | None:
    """Class name from a declared type: `const ns::Foo&` -> Foo, `std::unique_ptr<Foo>` -> Foo."""
    text = _TYPE_NOISE.sub(" ", text.strip().lstrip(":").strip().strip("'\"")).strip()  # TS `: Foo`
    text = text.split("|")[0].strip()  # `Foo | None`
    for _ in range(4):
        m = re.fullmatch(r"([\w:.]+)\s*[<\[](.*)[>\]]", text, re.S)
        if not m or re.split(r"::|\.", m.group(1))[-1] not in _WRAPPERS:
            break
        text = _first_arg(m.group(2)).strip()
    parts = _split_qualified(_TEMPLATE_ARGS.sub("", re.sub(r"\[.*\]", "", text)).replace(".", "::"))
    name = parts[-1] if parts else ""
    return name if _IDENT.fullmatch(name) else None


def _value_type(text: str) -> str | None:
    """Class a value is obviously an instance of: `new Foo(..)`, `Foo(..)`, `Foo::new()`, `&Foo{}`."""
    m = re.match(r"\s*(?:new\s+|&\s*)?([A-Za-z_][\w.:]*(?:<[^()]*>)?)\s*[({]", text)
    if not m:
        return None
    path = m.group(1)
    tm = re.fullmatch(r"([\w.:]+)<(.*)>", path)
    if tm and _split_qualified(tm.group(1))[-1] in _WRAPPERS:
        return _type_name(tm.group(2))
    parts = _split_qualified(_TEMPLATE_ARGS.sub("", path).replace(".", "::"))
    if len(parts) > 1 and parts[-1] in _FACTORIES:
        parts = parts[:-1]
    name = parts[-1] if parts else ""
    if name.startswith("New") and len(name) > 3 and name[3].isupper():
        name = name[3:]  # Go: NewServer() -> Server
    return name if _IDENT.fullmatch(name) else None


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


def _name_child(node: Node, field_name: str = "name") -> Node | None:
    found = node.child_by_field_name(field_name)
    if found is None:
        found = next((c for c in node.named_children if c.type in _NAME_TYPES), None)
    return found


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
        self.field_types: dict[str, dict[str, str]] = {}

    # ---- helpers -------------------------------------------------------------------------
    def _col(self, node: Node) -> int:
        row, byte_col = node.start_point
        return len(self.lines[row][:byte_col].decode("utf-8", "replace")) if row < len(self.lines) else byte_col

    def _code(self, start_row: int, end_row: int) -> str:
        return b"\n".join(self.lines[start_row:end_row + 1]).decode("utf-8", "replace")

    def _leading_comment(self, row: int) -> str:
        """The comment block that ends on the line right above `row` (0-based), if any."""
        hash_comments = self.lang.family in ("python", "ruby", "php")  # `#include`, `#if`, `#!` elsewhere
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
        if t == "expression_list" and parent.parent is not None and parent.parent.type == "assignment_statement":
            # Lua `local a, f = 1, function() end`: pair the value with its variable
            targets = parent.parent.named_children[0].named_children
            values = parent.named_children
            idx = next((i for i, v in enumerate(values) if v.id == node.id), -1)
            if 0 <= idx < len(targets):
                parts = [p for p in re.split(r"[.:]", _text(targets[idx])) if p]
                return parts[-2:] if parts and all(_IDENT.fullmatch(p) for p in parts) else None
            return None
        if t == "field" and self.lang.name == "lua":
            key = _text(parent.child_by_field_name("name"))
            return [key] if _IDENT.fullmatch(key) else None
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
        if t in _FIXED_NAMES:
            return [_FIXED_NAMES[t]]
        if t in ("arrow_function", "function_expression", "function", "generator_function", "function_definition"):
            assigned = self._assigned_name(node)
            if assigned:
                return assigned
            name = node.child_by_field_name("name")
            return [_text(name)] if name is not None else None
        name = _name_child(node)
        if name is None:
            return None
        if self.lang.name == "lua":  # `function M.add()` / `function M:method()`
            parts = [p for p in re.split(r"[.:]", _text(name)) if p]
            return parts[-2:] if parts and all(_IDENT.fullmatch(p) for p in parts) else None
        parts = [_text(name)]
        if t == "destructor_declaration":
            parts = ["~" + parts[0]]
        recv = node.child_by_field_name("receiver") if self.lang.name == "kotlin" else None
        if recv is not None:  # extension function `fun Cart.total()`
            idents = _IDENT.findall(_TEMPLATE_ARGS.sub("", _text(recv)))
            if idents:
                parts.insert(0, idents[-1])
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
                 "constant", "private_property_identifier", "simple_identifier"):
            return node, None, None
        if t == "navigation_expression":  # Swift / Kotlin `target.name`
            named = node.named_children
            suffix = node.child_by_field_name("suffix") or (named[-1] if named else None)
            target = node.child_by_field_name("target") or (named[0] if len(named) > 1 else None)
            name = _name_child(suffix, "suffix") if suffix is not None else None
            if name is None or target is None:
                return None
            return name, _text(target), "."
        if t in ("dot_index_expression", "method_index_expression"):  # Lua `t.f` / `t:m`
            name = node.child_by_field_name("field") or node.child_by_field_name("method")
            table = node.child_by_field_name("table")
            return (name, _text(table), ".") if name is not None else None
        if t in ("member_access_expression", "qualified_name"):  # C# `obj.Name` / `Ns.Type`
            name = node.child_by_field_name("name")
            obj = node.child_by_field_name("expression") or node.child_by_field_name("qualifier")
            if obj is None and node.children and node.children[0] != name:
                obj = node.children[0]  # `this` / `base` are anonymous tokens
            if name is None:
                return None
            res = self._callee(name)
            return (res[0], _text(obj) or None, ".") if res is not None else None
        if t == "generic_name":  # C# `Log<int>`
            name = _name_child(node)
            return (name, None, None) if name is not None else None
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

        fn = node.child_by_field_name("function") or node.child_by_field_name("name")
        if fn is None and self.lang.name in ("swift", "kotlin"):
            fn = node.named_children[0] if node.named_children else None
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

    # ---- declared types ------------------------------------------------------------------
    def _declared(self, node: Node) -> list[tuple[str, str]]:
        """(name, class name) pairs a declaration introduces; names may be `self.x` / `this.x` for members."""
        t = node.type
        type_node = node.child_by_field_name("type")
        if t == "variable_declarator" and type_node is None and node.parent is not None:
            type_node = node.parent.child_by_field_name("type")  # Java: `Foo a = ..., b;`
        value = node.child_by_field_name("value") or node.child_by_field_name("right")
        targets: list[Node] = []
        if t in ("declaration", "parameter_declaration", "optional_parameter_declaration", "field_declaration") \
                and self.lang.family == "c":
            for i, child in enumerate(node.children):
                if node.field_name_for_child(i) == "declarator":
                    targets.append(child)
        else:
            n = (node.child_by_field_name("name") or node.child_by_field_name("pattern")
                 or node.child_by_field_name("left"))
            if n is None and t == "typed_parameter":
                n = next((c for c in node.named_children if c.type == "identifier"), None)
            if n is not None and n.type == "expression_list":
                n = n.named_children[0] if n.named_child_count == 1 else None
            if value is not None and value.type == "expression_list":
                value = value.named_children[0] if value.named_child_count == 1 else None
            if n is not None:
                targets.append(n)
        out = []
        for target in targets:
            # C declarators: `*p`, `&r`, `p = value`
            while target.type in ("init_declarator", "pointer_declarator", "reference_declarator"):
                if target.type == "init_declarator":
                    value = target.child_by_field_name("value") or value
                inner = target.child_by_field_name("declarator")
                if inner is None:
                    inner = next((c for c in target.named_children if c.type in ("identifier", "field_identifier")), None)
                if inner is None:
                    break
                target = inner
            name = _text(target)
            if not (_IDENT.fullmatch(name) or re.fullmatch(r"(?:self|this)(?:\.|->)[A-Za-z_]\w*", name)):
                continue
            typ = _type_name(_text(type_node)) if type_node is not None else None
            if typ in (None, "auto", "var", "let", "Self") and value is not None and value.type != "argument_list":
                typ = _value_type(_text(value))
            if typ is None and value is not None and value.type == "argument_list" and type_node is not None:
                typ = _type_name(_text(type_node))  # C++ `Foo f(1);`
            if typ:
                out.append((name, typ))
        return out

    def _record_types(self, node: Node, scope: list[str], func: Function | None, in_class: bool) -> None:
        for name, typ in self._declared(node):
            if "." in name or "->" in name:  # self.x = Foo() inside a method
                if func is None or not func.scope:
                    continue
                key, name = ".".join(func.scope), re.split(r"\.|->", name)[-1]
            elif func is not None:
                prev = func.var_types.get(name)
                func.var_types[name] = typ if prev in (None, typ) else ""  # "" = conflicting types, don't use
                continue
            elif in_class and scope:
                key = ".".join(scope)  # a member declared in the class body
            else:
                continue
            fields = self.field_types.setdefault(key, {})
            prev = fields.get(name)
            fields[name] = typ if prev in (None, typ) else ""

    # ---- traversal -----------------------------------------------------------------------
    def _new_function(self, node: Node, parts: list[str], scope: list[str], in_class: bool) -> Function:
        full_scope = scope + parts[:-1]
        name = parts[-1]
        kind = "method" if in_class or len(parts) > 1 else "function"
        cls = full_scope[-1] if full_scope else None
        if name in self.lang.constructor_names or (cls is not None and name == cls):
            kind = "constructor"
        if self.lang.name in ("java", "csharp") and node.type == "constructor_declaration":
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
                name_node = _name_child(node, field_name) if field_name else None
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
            elif func is not None:
                if t in _BRANCHES:
                    if not (t in ("case_statement", "switch_label", "switch_entry", "when_entry", "match_arm")
                            and _DEFAULT_CASE.match(node.text)):
                        func.complexity += 1
                elif t in ("binary_expression", "binary") and _text(node.child_by_field_name("operator")) in _LOGICAL:
                    func.complexity += 1
            if t in _DECLS:
                self._record_types(node, scope, func, in_class)

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


def _string_value(node: Node | None) -> str | None:
    if node is None or node.type != "string":
        return None
    frag = next((c for c in node.named_children if c.type == "string_fragment"), None)
    return _text(frag) if frag is not None else None


def _require_spec(node: Node | None) -> str | None:
    """`require("./x")` -> "./x"."""
    if node is None or node.type != "call_expression" or _text(node.child_by_field_name("function")) != "require":
        return None
    args = node.child_by_field_name("arguments")
    return _string_value(args.named_children[0]) if args is not None and args.named_children else None


def _bindings(lang: Language, root: Node) -> dict[str, tuple[str, str | None]]:
    """Names that top-level imports bring into a Python or JS/TS file."""
    out: dict[str, tuple[str, str | None]] = {}
    for node in root.named_children:
        t = node.type
        if lang.family == "python" and t == "import_from_statement":
            spec = _text(node.child_by_field_name("module_name")).replace(" ", "")
            for i, child in enumerate(node.children):
                if node.field_name_for_child(i) != "name":
                    continue
                if child.type == "aliased_import":
                    out[_text(child.child_by_field_name("alias"))] = (spec, _text(child.child_by_field_name("name")))
                else:
                    out[_text(child)] = (spec, _text(child))
        elif lang.family == "python" and t == "import_statement":
            for i, child in enumerate(node.children):
                if node.field_name_for_child(i) != "name":
                    continue
                if child.type == "aliased_import":
                    out[_text(child.child_by_field_name("alias"))] = (_text(child.child_by_field_name("name")), None)
                else:  # `import a.b` binds `a`; calls like `a.b.f()` are resolved through the qualifier
                    name = _text(child)
                    out[name.split(".")[0]] = (name.split(".")[0], None)
        elif lang.family == "js" and t == "import_statement":
            spec = _string_value(node.child_by_field_name("source"))
            clause = next((c for c in node.named_children if c.type == "import_clause"), None)
            if not spec or clause is None:
                continue
            for c in clause.named_children:
                if c.type == "identifier":  # default import: assume it is named like the binding
                    out[_text(c)] = (spec, _text(c))
                elif c.type == "namespace_import":
                    ident = next((x for x in c.named_children if x.type == "identifier"), None)
                    if ident is not None:
                        out[_text(ident)] = (spec, None)
                elif c.type == "named_imports":
                    for sp in c.named_children:
                        if sp.type == "import_specifier":
                            name = _text(sp.child_by_field_name("name"))
                            out[_text(sp.child_by_field_name("alias") or sp.child_by_field_name("name"))] = (spec, name)
        elif lang.family == "js" and t in ("lexical_declaration", "variable_declaration"):
            for decl in node.named_children:
                if decl.type != "variable_declarator":
                    continue
                spec = _require_spec(decl.child_by_field_name("value"))
                target = decl.child_by_field_name("name")
                if not spec or target is None:
                    continue
                if target.type == "identifier":
                    out[_text(target)] = (spec, None)
                elif target.type == "object_pattern":
                    for c in target.named_children:
                        if c.type == "shorthand_property_identifier_pattern":
                            out[_text(c)] = (spec, _text(c))
                        elif c.type == "pair_pattern":
                            out[_text(c.child_by_field_name("value"))] = (spec, _text(c.child_by_field_name("key")))
    return out


def extract_file(lang: Language, parser, rel_path: str, source: bytes) -> FileInfo:
    tree = parser.parse(source)
    ex = _Extractor(lang, rel_path, source)
    ex.run(tree.root_node)
    functions = ex.functions
    if ex.toplevel is not None:
        ex.toplevel.code = ""  # top-level code is shown via its call list only
        functions = [ex.toplevel] + functions
    return FileInfo(rel_path, lang, source.count(b"\n") + 1, _imports(source), functions, ex.classes,
                    _bindings(lang, tree.root_node), {k: v for k, v in ex.field_types.items() if v})

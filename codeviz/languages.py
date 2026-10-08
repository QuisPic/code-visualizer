"""Per-language tree-sitter node types used to find functions, scopes and calls."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Language:
    name: str  # tree-sitter-language-pack grammar name
    family: str  # languages in the same family may call each other (c <-> cpp, js <-> ts)
    extensions: tuple[str, ...]
    functions: frozenset[str]
    # node type -> field that holds the scope's name (None = anonymous scope)
    scopes: dict[str, str | None] = field(default_factory=dict)
    calls: frozenset[str] = frozenset()
    constructor_calls: frozenset[str] = frozenset()
    # method names that act as a class's constructor
    constructor_names: frozenset[str] = frozenset()
    # receivers that refer to the enclosing class
    self_names: frozenset[str] = frozenset({"this", "self"})


def _fs(*items: str) -> frozenset[str]:
    return frozenset(items)


_JS_FUNCS = _fs(
    "function_declaration",
    "generator_function_declaration",
    "method_definition",
    "function_expression",
    "function",
    "arrow_function",
    "generator_function",
)
_JS_SCOPES = {"class_declaration": "name", "class": "name", "abstract_class_declaration": "name",
              "interface_declaration": "name", "internal_module": "name", "module": "name"}
_C_SCOPES = {"class_specifier": "name", "struct_specifier": "name", "union_specifier": "name",
             "namespace_definition": "name"}

LANGUAGES: list[Language] = [
    Language("python", "python", (".py", ".pyw"),
             _fs("function_definition"),
             {"class_definition": "name"},
             _fs("call"), constructor_names=_fs("__init__"), self_names=_fs("self", "cls")),
    Language("javascript", "js", (".js", ".jsx", ".mjs", ".cjs", ".jsxinc"),
             _JS_FUNCS, _JS_SCOPES, _fs("call_expression"), _fs("new_expression"),
             _fs("constructor")),
    Language("typescript", "js", (".ts", ".mts", ".cts"),
             _JS_FUNCS, _JS_SCOPES, _fs("call_expression"), _fs("new_expression"),
             _fs("constructor")),
    Language("tsx", "js", (".tsx",),
             _JS_FUNCS, _JS_SCOPES, _fs("call_expression"), _fs("new_expression"),
             _fs("constructor")),
    Language("c", "c", (".c",),
             _fs("function_definition"), {"struct_specifier": "name"}, _fs("call_expression")),
    Language("cpp", "c", (".cpp", ".cc", ".cxx", ".c++", ".hpp", ".hh", ".hxx", ".h", ".inl", ".ipp", ".mm"),
             _fs("function_definition"), _C_SCOPES, _fs("call_expression"), _fs("new_expression")),
    Language("go", "go", (".go",),
             _fs("function_declaration", "method_declaration"),
             {}, _fs("call_expression")),
    Language("rust", "rust", (".rs",),
             _fs("function_item"),
             {"impl_item": "type", "trait_item": "name", "mod_item": "name"},
             _fs("call_expression"), constructor_names=_fs("new"), self_names=_fs("self", "Self")),
    Language("java", "java", (".java",),
             _fs("method_declaration", "constructor_declaration"),
             {"class_declaration": "name", "interface_declaration": "name", "enum_declaration": "name",
              "record_declaration": "name"},
             _fs("method_invocation"), _fs("object_creation_expression")),
    Language("ruby", "ruby", (".rb",),
             _fs("method", "singleton_method"),
             {"class": "name", "module": "name"},
             _fs("call"), constructor_names=_fs("initialize"), self_names=_fs("self")),
    Language("php", "php", (".php",),
             _fs("function_definition", "method_declaration"),
             {"class_declaration": "name", "interface_declaration": "name", "trait_declaration": "name",
              "namespace_definition": "name"},
             _fs("function_call_expression", "member_call_expression", "scoped_call_expression",
                 "nullsafe_member_call_expression"),
             _fs("object_creation_expression"), _fs("__construct"), _fs("$this", "self", "static")),
]

BY_EXTENSION: dict[str, Language] = {ext: lang for lang in LANGUAGES for ext in lang.extensions}

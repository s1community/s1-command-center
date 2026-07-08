"""Static wiring check: every `command=self._x` callback on a widget must
resolve to a real method on the enclosing class.

This catches the whole class of "app crashes on launch because a button points
at a method that was renamed/deleted" bugs — without needing a display to
actually build the Tk UI. (A real such bug shipped once: a button referenced
`self._mangle_rename` after the method header was accidentally removed; this
test fails on exactly that.)
"""
import ast
import os

PAGES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "pages.py")


def _class_methods(cls: ast.ClassDef) -> set:
    return {n.name for n in cls.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def test_command_callbacks_resolve_to_methods():
    tree = ast.parse(open(PAGES).read())
    failures = []
    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        methods = _class_methods(cls)
        for node in ast.walk(cls):
            # match keyword: command=self._something  (direct method handle)
            if not isinstance(node, ast.keyword):
                continue
            if node.arg not in ("command", "callback"):
                continue
            v = node.value
            if (isinstance(v, ast.Attribute)
                    and isinstance(v.value, ast.Name)
                    and v.value.id == "self"):
                if v.attr not in methods:
                    failures.append(f"{cls.name}.{v.attr}")
    assert not failures, (
        "command/callback points at a missing method: " + ", ".join(failures))

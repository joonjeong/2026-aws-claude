"""독립성 게이트 — datalake는 hub 코드를 절대 import하지 않는다 (설계 §4)."""

import ast
from pathlib import Path

import datalake

FORBIDDEN = ("app", "hub")
PKG_ROOT = Path(datalake.__file__).resolve().parent


def _imported_names(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module


def test_no_hub_imports():
    offenders = []
    for py in PKG_ROOT.rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for name in _imported_names(tree):
            if any(name == f or name.startswith(f + ".") for f in FORBIDDEN):
                offenders.append(f"{py.relative_to(PKG_ROOT)}: {name}")
    assert not offenders, f"hub 코드 import 발견: {offenders}"

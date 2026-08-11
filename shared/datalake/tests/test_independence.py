"""독립성·자기완결 게이트.

1) hub/app/labkit import 금지 — hub 코드와의 결합 차단.
2) 패키지 내부 상호 import 금지 — 원천당 파일 하나가 자기완결이어야 한다.
"""

import ast
from pathlib import Path

import datalake

FORBIDDEN = ("app", "hub", "labkit")
PKG_ROOT = Path(datalake.__file__).resolve().parent


def _imports(py: Path):
    tree = ast.parse(py.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from ((alias.name, 0) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            yield (node.module or "", node.level)


def test_no_hub_imports():
    offenders = [
        f"{py.name}: {name}"
        for py in PKG_ROOT.glob("*.py")
        for name, _level in _imports(py)
        if any(name == f or name.startswith(f + ".") for f in FORBIDDEN)
    ]
    assert not offenders, f"hub/labkit import 발견: {offenders}"


def test_modules_are_self_contained():
    offenders = [
        f"{py.name}: {name or '(relative)'}"
        for py in PKG_ROOT.glob("*.py")
        if py.name != "__init__.py"
        for name, level in _imports(py)
        if level > 0 or name == "datalake" or name.startswith("datalake.")
    ]
    assert not offenders, f"패키지 내부 import 발견 (자기완결 위반): {offenders}"

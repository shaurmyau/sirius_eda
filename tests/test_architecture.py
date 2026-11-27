"""Архитектурный тест: service.py не зависит от fastapi/sqlalchemy."""
import ast
from pathlib import Path

FORBIDDEN = ("fastapi", "sqlalchemy")
MODULES = Path(__file__).resolve().parent.parent / "app" / "modules"


def test_services_are_pure():
    services = sorted(MODULES.glob("*/service.py"))
    assert len(services) == 7
    for path in services:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for n in names:
                assert not n.startswith(FORBIDDEN), f"{path.name}: {n}"

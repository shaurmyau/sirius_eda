"""
Архитектурный тест: service.py не должен импортировать fastapi и sqlalchemy.
"""
import ast
from pathlib import Path

FORBIDDEN = ("fastapi", "sqlalchemy")
MODULES_DIR = Path(__file__).resolve().parent.parent / "app" / "modules"


def test_services_do_not_import_frameworks():
    services = sorted(MODULES_DIR.glob("*/service.py"))
    assert len(services) == 4

    for path in services:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert not name.startswith(FORBIDDEN), f"{path.name}: запрещённый импорт {name}"

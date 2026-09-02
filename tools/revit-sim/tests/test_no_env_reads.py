"""No production sim module reads the environment: test hooks cannot be armed by
an env var on a workstation (they exist only behind the explicit --control-port),
and no execution behaviour depends on ambient configuration."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "revit_sim"


def test_no_module_reads_os_environ():
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in ("environ", "getenv", "putenv"):
                offenders.append(f"{path.name}:{node.lineno}")
            if isinstance(node, ast.Name) and node.id in ("getenv", "environ"):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == [], offenders

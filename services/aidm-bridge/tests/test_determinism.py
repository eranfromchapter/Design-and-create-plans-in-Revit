"""Purity by AST (the sim's test_no_env_reads pattern): the pure modules never import clocks,
randomness or the environment; only server.py reads os.environ; render.py and aidm.py touch
time only for their injectable monotonic/sleep defaults."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "aidm_bridge"
PURE = ["control_maps", "prompts", "guard", "selection", "csi", "catalogs", "golden_render"]
FORBIDDEN_MODULES = {"random", "time", "datetime", "os", "secrets", "uuid"}


def _imports(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_pure_modules_import_no_rng_clock_or_environment():
    for module in PURE:
        tree = ast.parse((SRC / f"{module}.py").read_text())
        assert not (_imports(tree) & FORBIDDEN_MODULES), module


def test_only_server_reads_environ():
    for path in SRC.glob("*.py"):
        source = path.read_text()
        if path.stem == "server":
            assert "os.environ" in source
            continue
        assert "os.environ" not in source and "getenv" not in source, path.name


def test_render_and_aidm_touch_only_monotonic_and_sleep():
    for module in ("render", "aidm"):
        tree = ast.parse((SRC / f"{module}.py").read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if node.value.id == "time":
                    assert node.attr in {"monotonic", "sleep"}, (module, node.attr)

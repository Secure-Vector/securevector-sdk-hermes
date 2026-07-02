"""Drift guard: HERMES_BUILTINS vs a real hermes-agent install.

HERMES_BUILTINS was extracted from the hermes-agent 0.18.0 sdist. Tool names
Hermes actually dispatches must be resolvable by our permission layer, so any
tool present in a live registry but missing from our table is drift — fix the
table (and re-check the app-side registry rows) before raising the version pin.

Skips when hermes-agent isn't importable (unit CI installs the SDK with
--no-deps); runs on any full local install, which is exactly the pre-release
empirical gate story #183 requires.
"""

import ast
import pathlib

import pytest

from securevector_sdk_hermes.tool_id import HERMES_BUILTINS

hermes_tools = pytest.importorskip(
    "tools.registry", reason="hermes-agent not installed; drift check needs it"
)


def _registered_names_from_source() -> set:
    """AST-scan the installed hermes tools/ package for registry.register()
    calls — same extraction that produced HERMES_BUILTINS, but against the
    *installed* version, so a pin bump makes drift fail loudly here."""
    pkg_dir = pathlib.Path(hermes_tools.__file__).parent
    names = set()
    for py in pkg_dir.rglob("*.py"):
        try:
            tree = ast.parse(py.read_text())
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "register":
                name = None
                if node.args and isinstance(node.args[0], ast.Constant):
                    name = node.args[0].value
                for kw in node.keywords:
                    if kw.arg == "name" and isinstance(kw.value, ast.Constant):
                        name = kw.value.value
                if isinstance(name, str):
                    names.add(name)
    return names


def test_no_registered_tool_is_missing_from_builtins():
    live = _registered_names_from_source()
    assert live, "no registrations found — extraction broke or layout changed"
    missing = sorted(live - set(HERMES_BUILTINS))
    assert not missing, (
        f"hermes-agent registers tools missing from HERMES_BUILTINS: {missing} — "
        "update tool_id.py (and the app-side hermes registry rows)"
    )

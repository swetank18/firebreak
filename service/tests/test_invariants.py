"""THE INVARIANT THAT MAKES THE DOMAIN-AGNOSTIC CLAIM TRUE.

`EXECUTION.md` section 5: nothing in `decision/` imports anything from `city/`.
The decision layer consumes a graph and a kernel, never a simulator. If an
intervention scorer needs to know it is looking at a water pump rather than a
node with a dependency profile, the design is wrong and the claim is a lie.

Two tests, because the first has an obvious loophole: a string literal comparing
against "water" passes an import check and still couples the engine just as
tightly. Both are AST-level, so a comment mentioning a layer is fine and an
executable line naming one is not.
"""

from __future__ import annotations

import ast
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[2]
DECISION = REPO / "decision"
LAYERS = {"power", "water", "transport", "telecom", "health"}
FORBIDDEN_IMPORT_ROOTS = {"city"}


def _sources():
    return sorted(DECISION.rglob("*.py"))


def test_decision_files_exist():
    """Guard against the test silently passing because it found nothing."""
    assert _sources(), "no python files found under decision/ — the test is not testing anything"


def test_decision_imports_nothing_from_city():
    offenders = []
    for path in _sources():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.split(".")[0] in FORBIDDEN_IMPORT_ROOTS:
                        offenders.append(f"{path.name}:{node.lineno} import {a.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in FORBIDDEN_IMPORT_ROOTS:
                    offenders.append(f"{path.name}:{node.lineno} from {node.module}")
    assert not offenders, (
        "decision/ imports from city/: " + "; ".join(offenders) + ". The decision layer "
        "consumes a graph and a kernel, never a simulator."
    )


def test_no_executable_line_in_decision_names_a_layer():
    """The loophole test. A docstring may say 'water'; an `if` may not.

    Docstrings are excluded deliberately — the files explain themselves in
    domain terms, and that is documentation, not coupling.
    """
    offenders = []
    for path in _sources():
        tree = ast.parse(path.read_text(), filename=str(path))
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                d = ast.get_docstring(node, clean=False)
                if d is not None and isinstance(node.body[0], ast.Expr):
                    docstrings.add(id(node.body[0].value))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) in docstrings:
                    continue
                if node.value in LAYERS:
                    offenders.append(f"{path.name}:{node.lineno} {node.value!r}")
    assert not offenders, (
        "executable lines in decision/ name a layer: " + "; ".join(offenders) + ". "
        "Use a domain-neutral contract field (Node.protected_class, criticality_weight, "
        "population_served) instead — see docs/DECISIONS.md."
    )


# --------------------------------------------------------------------------
# Cross-lane coupling, frozen.
#
# AGENTS.md rule 2: "Code against contracts, not against other lanes' code. If
# you are importing from another lane's internals, stop — that is a contract
# gap." Two such imports exist and both are deliberate. This test does not
# forbid them; it freezes them, so a THIRD one has to be argued for rather than
# appearing by accident.
# --------------------------------------------------------------------------

PRODUCERS = ("city", "inference", "decision")

# module -> why it is allowed to cross a lane boundary
ALLOWED_CROSS_LANE = {
    # Lane B reuses the engine's state containers to reconstruct observable
    # state. A coupling, not a leak: no ground truth crosses. Recorded in
    # docs/LIMITATIONS.md as the contract gap it is.
    ("inference", "city.engine.state"),
    # The canonical identity for flow-sibling relations, which have no Edge and
    # therefore no Edge.id. Two lanes deriving it separately is what cost H1 its
    # entire signal, so it is deliberately ONE helper shared by both sides.
    ("decision", "inference.relations"),
}


def _imported_modules(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module)
    return out


def test_cross_lane_imports_are_the_two_we_signed_up_for():
    found = set()
    for pkg in PRODUCERS:
        for path in sorted((REPO / pkg).rglob("*.py")):
            for mod in _imported_modules(path):
                root = mod.split(".")[0]
                if root in PRODUCERS and root != pkg:
                    found.add((pkg, mod))
    new = found - ALLOWED_CROSS_LANE
    assert not new, (
        f"new cross-lane imports: {sorted(new)}. A producer package should reach for "
        "contracts/, not for another lane's internals. If this one is genuinely right, "
        "add it to ALLOWED_CROSS_LANE with the reason and record it in docs/DECISIONS.md."
    )
    stale = ALLOWED_CROSS_LANE - found
    assert not stale, (
        f"allowlisted couplings that no longer exist: {sorted(stale)}. Delete them from "
        "ALLOWED_CROSS_LANE so the list keeps meaning something."
    )

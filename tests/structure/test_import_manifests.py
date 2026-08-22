"""Each package declares the packages it may import, and the guard checks it.

Tier 3 of the structural guard work.  ``tests/core/test_module_conventions.py``
states rules about a *module*; this file states one rule about a *package*.

Why a manifest and not a rank number.  ``accounts`` and ``telemetry`` are
genuinely independent: neither imports the other, and neither is above the
other.  A rank number would have to give them one, which would say something
untrue.  A list of neighbours says only what is true, and the shape of the
whole tree is then a property to derive — no cycle — rather than a number to
maintain.

Three checks, and the second is the one that keeps the file honest over years:

1. Every cross-package import is declared.  This is the upper bound.
2. Every declaration is used.  A manifest that only checks the upper bound
   decays into a wish list, because removing the last import of a neighbour
   leaves no signal.  A stale entry is a lie about the shape.
3. The declared graph has no cycle.  Two packages that may import each other
   are one package with a line drawn through it.

``migrations/`` is excluded because Django writes those files.  The suite is
not covered at all: it lives in ``tests/``, outside every package, precisely so
that a test which reaches across packages breaks no manifest.
"""

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Every package a manifest governs.  A new package added to the repository
#: and left out of this tuple is caught by ``test_every_package_declares``,
#: which reads the directories rather than this list.
PACKAGES = (
    "shared",
    "data",
    "core",
    "accounts",
    "telemetry",
    "corpus",
    "search",
    "web",
)


def _package_dirs() -> list[Path]:
    """Every top-level directory that is a Python package and not the project.

    Read off the filesystem, so a ninth package cannot appear without this
    file noticing.  ``code_chronicle`` holds the settings and the root URLconf
    — it is the Django project, which by construction imports everything.
    """
    return sorted(
        path
        for path in REPO_ROOT.iterdir()
        if path.is_dir()
        and (path / "__init__.py").exists()
        and path.name not in {"code_chronicle", "tests", "venv"}
        and not path.name.startswith(".")
    )


def _manifest(package: str) -> tuple[str, ...]:
    """``ALLOWED_IMPORTS`` read with ``ast``, not by importing the package.

    Importing would need Django's settings and would run every ``ready()``.
    The manifest is a literal tuple of literal strings, so reading it is
    exact.
    """
    tree = ast.parse((REPO_ROOT / package / "__init__.py").read_text(encoding="utf-8"))
    for node in tree.body:
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        if isinstance(target, ast.Name) and target.id == "ALLOWED_IMPORTS":
            assert value is not None, f"{package}: ALLOWED_IMPORTS has no value"
            return tuple(ast.literal_eval(value))
    raise AssertionError(
        f"{package}/__init__.py declares no ALLOWED_IMPORTS.  Add one naming "
        f"the packages {package} may import, or an empty tuple if it imports "
        "none of them."
    )


def _imports(package: str) -> dict[str, list[str]]:
    """``{other_package: ["relpath:line name", ...]}`` for one package."""
    found: dict[str, list[str]] = {}
    for path in sorted((REPO_ROOT / package).rglob("*.py")):
        if "migrations" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            elif isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            else:
                continue
            for name in names:
                root = name.split(".")[0]
                if root in PACKAGES and root != package:
                    rel = path.relative_to(REPO_ROOT).as_posix()
                    found.setdefault(root, []).append(f"{rel}:{node.lineno}  {name}")
    return found


def test_every_package_declares() -> None:
    """Every package directory carries a manifest, and PACKAGES names it."""
    on_disk = {path.name for path in _package_dirs()}
    assert on_disk == set(PACKAGES), (
        f"The packages on disk are {sorted(on_disk)} but PACKAGES says "
        f"{sorted(PACKAGES)}.\n\nHow to fix: add the new package to PACKAGES "
        "here, give it an ALLOWED_IMPORTS in its __init__.py, and place it in "
        "the table in CLAUDE.md."
    )
    for package in PACKAGES:
        _manifest(package)


def test_no_undeclared_import() -> None:
    """Every cross-package import appears in the importing package's manifest."""
    offenders: list[str] = []
    for package in PACKAGES:
        allowed = set(_manifest(package))
        for other, sites in sorted(_imports(package).items()):
            if other not in allowed:
                offenders.append(f"{package} -> {other}, which {package} does not declare:")
                offenders.extend(f"    {site}" for site in sites)
    assert not offenders, (
        "Imports across a package boundary that no manifest allows:\n  "
        + "\n  ".join(offenders)
        + "\n\nHow to fix: if the dependency is right, add the package to "
        "ALLOWED_IMPORTS in the importing package's __init__.py — but check "
        "first that it does not point upward.  If it does, the piece both "
        "sides need belongs lower down: move it to a package they can both "
        "import, or pass it in (corpus takes its tier gate as a "
        "Callable[[str], bool] rather than importing accounts for it)."
    )


def test_no_unused_declaration() -> None:
    """Every declared neighbour is one the package really imports."""
    offenders: list[str] = []
    for package in PACKAGES:
        used = set(_imports(package))
        for other in _manifest(package):
            if other not in used:
                offenders.append(f"{package} declares {other}, and imports nothing from it")
    assert not offenders, (
        "Stale manifest entries:\n  "
        + "\n  ".join(offenders)
        + "\n\nHow to fix: delete the entry.  A manifest is a statement about "
        "the shape of the code, and an entry nothing uses states a dependency "
        "that is not there — which is how a manifest turns into a wish list."
    )


def test_the_declared_graph_has_no_cycle() -> None:
    """No package can reach itself through the declared edges.

    Depth-first, carrying the path, so the failure names the cycle rather than
    reporting that one exists.
    """
    graph = {package: _manifest(package) for package in PACKAGES}
    cycles: list[str] = []

    def walk(node: str, path: tuple[str, ...]) -> None:
        for neighbour in graph[node]:
            if neighbour in path:
                start = path.index(neighbour)
                cycles.append(" -> ".join(path[start:] + (neighbour,)))
                continue
            walk(neighbour, path + (neighbour,))

    for package in PACKAGES:
        walk(package, (package,))

    assert not cycles, (
        "Cycles in the declared package graph:\n  "
        + "\n  ".join(sorted(set(cycles)))
        + "\n\nHow to fix: two packages that may import each other are one "
        "package with a line drawn through it.  Find the piece both sides "
        "need and move it below them both."
    )

"""Structural guards on the Python packages, enforced with ``ast``.

These are not behaviour tests.  They state three rules about the *shape* of
the codebase, so that a change which breaks one fails in the normal suite
rather than in a review six months later.

Why a pytest test and not a ruff rule: ruff runs in ``pre-commit``, which is
local and a person can skip.  ``.github/workflows/publish.yml`` runs ``pytest``
and gates the deploy on it, so a rule written here runs everywhere the suite
runs.  Ruff still owns the rules it already has (``F401`` unused imports,
``I001`` import order); nothing below repeats them.

The rules:

1. **No import inside a function body.**  A lazy import hides a dependency the
   module really has, and it moves an ``ImportError`` from start-up to the
   first call — which is often in production, on a path tests do not take.
   One file is exempt (see ``INLINE_IMPORT_EXEMPT``).
2. **No relative import.**  ``from .regulation import x`` and
   ``from core.views.regulation import x`` name the same module, and only the
   second says so.  The first makes a module's dependencies unreadable without
   knowing which directory the file is in, it moves when the file moves, and —
   the reason this rule exists — it made rule 3 look satisfied when it was
   not: seven private helpers were read across module boundaries in
   ``core/views`` and the relative form was hiding every one of them.
3. **No import of a private name across a module boundary.**  A leading
   underscore is the author saying "nobody outside reads this".  A second
   module reading it anyway means the split is in the wrong place: either the
   name is public and should say so, or it belongs in the other module.
4. **No top-level name defined in two modules.**  Either it is one thing
   written twice, so a fix to one leaves the other wrong, or it is two things
   under one name, so a reader who has met the first misreads the second.
5. **No module-level constant duplicated by value.**  Two files that compile
   the same regex under the same name is a copy that rots — one gets a fix,
   the other does not, and the symptom appears far from the duplication.

Each failure names the fix.  Add an exemption only when the rule is genuinely
wrong for that file, and write down why in the same commit.
"""

import ast
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The Python packages these rules cover.  ``code_chronicle`` (settings) is
#: deliberately out of scope for rules 2 and 3: a settings module re-declares
#: names from ``base.py`` on purpose, which is what an override *is*.
APP_PACKAGES = ("api", "core", "services", "config")

#: The one file allowed an import inside a function body.  Django calls
#: ``AppConfig.ready()`` once the app registry is populated, and it is the only
#: correct moment to import a module that touches models or registers a signal
#: receiver.  A module-top import there runs before the registry exists and
#: raises ``AppRegistryNotReady``.  Django's own documentation prescribes the
#: deferred import, so this is the framework's rule, not a local shortcut.
INLINE_IMPORT_EXEMPT = frozenset({"core/apps.py"})


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def app_files() -> list[Path]:
    """Every hand-written module in the app packages.

    ``migrations/`` is excluded because Django writes those files, and
    ``tests/`` because a test may legitimately import a private name — that is
    what a unit test of a private helper does.
    """
    files: list[Path] = []
    for package in APP_PACKAGES:
        root = REPO_ROOT / package
        if not root.exists():
            continue
        files.extend(
            path
            for path in sorted(root.rglob("*.py"))
            if "migrations" not in path.parts and "tests" not in path.parts
        )
    return files


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


class _InlineImportFinder(ast.NodeVisitor):
    """Records the line of every import lexically inside a function body.

    Depth is a counter rather than a flag so an import in a nested function is
    recorded once, not once per enclosing function.
    """

    def __init__(self) -> None:
        self.depth = 0
        self.hits: list[int] = []

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.depth += 1
        self.generic_visit(node)
        self.depth -= 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _record(self, node: ast.Import | ast.ImportFrom) -> None:
        if self.depth > 0:
            self.hits.append(node.lineno)

    def visit_Import(self, node: ast.Import) -> None:
        self._record(node)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self._record(node)
        self.generic_visit(node)


def test_no_function_body_imports() -> None:
    """Every import sits at module level, outside ``INLINE_IMPORT_EXEMPT``.

    A module-top ``try: import x / except ImportError:`` is *not* a function
    body import and passes — that is the supported way to reach an optional
    dependency (see ``api/search/engine.py`` and rapidfuzz).
    """
    offenders: list[str] = []
    for path in app_files():
        if _rel(path) in INLINE_IMPORT_EXEMPT:
            continue
        finder = _InlineImportFinder()
        finder.visit(_parse(path))
        offenders.extend(f"{_rel(path)}:{line}" for line in finder.hits)
    assert not offenders, (
        "Imports inside a function body:\n  "
        + "\n  ".join(offenders)
        + "\n\nHow to fix: move the import to the top of the module.  If it is "
        "there to break an import cycle, the cycle is the defect — move the "
        "shared piece down into a module both sides can import (as "
        "core/html_tags.py and core/code_names.py do).  If the dependency is "
        "genuinely optional, guard it at module top with try/except "
        "ImportError.  Extend INLINE_IMPORT_EXEMPT only for a framework "
        "contract, and say which one in the comment there."
    )


def test_no_relative_imports() -> None:
    """Every import names its module in full.

    ``core/views/__init__.py`` re-exports sixteen modules and is the obvious
    place to argue for the short form, but it is also the place the short form
    costs most: the package's own ``__init__`` is what a reader opens to learn
    what ``core.views`` contains.
    """
    offenders: list[str] = []
    for path in app_files():
        for node in ast.walk(_parse(path)):
            if isinstance(node, ast.ImportFrom) and node.level:
                dots = "." * node.level
                offenders.append(
                    f"{_rel(path)}:{node.lineno}  from {dots}{node.module or ''} import ..."
                )
    assert not offenders, (
        "Relative imports:\n  "
        + "\n  ".join(offenders)
        + "\n\nHow to fix: write the module's full dotted path — "
        "'from core.views.regulation import x', not 'from .regulation import "
        "x'.  A package's own __init__.py is not an exception; it imports "
        "'core.views.pages' the same way anything else does."
    )


def test_no_private_cross_module_imports() -> None:
    """No module reaches for another module's underscore-prefixed name.

    Only imports of first-party modules are checked; a third-party library's
    private surface is that library's problem, and its own tests do the same.
    """
    offenders: list[str] = []
    for path in app_files():
        for node in ast.walk(_parse(path)):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if node.level:  # already refused, by name, in test_no_relative_imports
                continue
            if node.module.split(".")[0] not in APP_PACKAGES:
                continue
            private = sorted(a.name for a in node.names if a.name.startswith("_"))
            if private:
                offenders.append(
                    f"{_rel(path)}:{node.lineno}  from {node.module} "
                    f"import {', '.join(private)}"
                )
    assert not offenders, (
        "Imports of a private name across a module boundary:\n  "
        + "\n  ".join(offenders)
        + "\n\nHow to fix: decide which the name is.  If two modules need it, "
        "it is public — drop the underscore and update the call sites (add it "
        "to __all__ if the module has one).  If it should stay private, the "
        "caller wants something else: give it a public function that wraps "
        "the private one, or move the private helper to the caller."
    )


def _constant_value_key(node: ast.AST) -> str | None:
    """A comparable key for a constant's *value*, or ``None`` to ignore it.

    Covered: a compiled regex (pattern plus flags), a string, and a set, dict,
    tuple or list literal.  Not covered: bare numbers and booleans.  The line
    is drawn by kind, not by length — a duplicated ``frozenset({"OBC_2006"})``
    is a real collision at any size, whereas ``0.8`` is a threshold, a ratio
    and a margin in unrelated modules and means nothing shared.
    """
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "compile":
            if not node.args or not isinstance(node.args[0], ast.Constant):
                return None
            flags = ast.unparse(node.args[1]) if len(node.args) > 1 else ""
            return f"re.compile|{node.args[0].value!r}|{flags}"
        if isinstance(func, ast.Name) and func.id in ("frozenset", "set"):
            return f"{func.id}|{ast.unparse(node)}"
        return None
    if isinstance(node, (ast.Set, ast.Dict, ast.Tuple, ast.List)):
        return f"literal|{ast.unparse(node)}"
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
        # A short string is usually a label, not a shared surface.
        return f"str|{node.value!r}" if len(node.value) >= 12 else None
    return None


def _is_constant_name(name: str) -> bool:
    """UPPER_SNAKE_CASE, which is what this repo calls a constant.

    The case test is what keeps ``register``, ``logger`` and ``urlpatterns``
    out of the duplicate-name check.  Those are Django contracts: every
    template-tag module must bind ``register``, and a rule that flagged them
    could only be satisfied by an allowlist as long as the list of modules.
    """
    return bool(name) and name.upper() == name and name[0].isalpha()


def _is_management_command(node: ast.ClassDef) -> bool:
    """A Django management command, which must be named ``Command``.

    Django's loader imports ``Command`` from the module named after the
    command, so eleven of these exist and none of them may be renamed.  The
    exemption is read off the class's own base rather than off a list of file
    paths, so a twelfth command needs no edit here — and a class that merely
    happens to be called ``Command`` is still refused.
    """
    if node.name != "Command":
        return False
    return any(ast.unparse(base).endswith("BaseCommand") for base in node.bases)


def _module_names() -> dict[str, list[str]]:
    """``{name: [relpath, ...]}`` over top-level functions, classes, constants."""
    by_name: dict[str, list[str]] = defaultdict(list)
    for path in app_files():
        for node in _parse(path).body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                by_name[node.name].append(_rel(path))
            elif isinstance(node, ast.ClassDef):
                if not _is_management_command(node):
                    by_name[node.name].append(_rel(path))
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and _is_constant_name(target.id):
                        by_name[target.id].append(_rel(path))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if _is_constant_name(node.target.id):
                    by_name[node.target.id].append(_rel(path))
    return by_name


def test_no_duplicate_top_level_names() -> None:
    """One name is defined in one module.

    Two modules holding a ``_clean_email`` is one of two faults, and both are
    worth failing on.  Either they are the same thing written twice, and a fix
    to one leaves the other wrong; or they are different things wearing one
    name, and a reader who has met the first will misread the second.  The
    first is repaired by moving the code down to a module both can import; the
    second by naming the two apart.

    Functions, classes and UPPER_SNAKE_CASE constants are all collected.  Two
    kinds of name are not:

    * A **lower-case module-level binding** — ``register``, ``logger``,
      ``urlpatterns``.  Django requires the name in each module that has one,
      so nothing about a duplicate is informative.
    * A **management command's ``Command``**, recognised by its base class
      rather than by its path (see :func:`_is_management_command`).

    There is no allowlist, and that is the point of the test rather than an
    omission.  An allowlist turns "do not do this" into "do not do this
    without adding a line", and the line is cheaper than the reorg every time.
    """
    duplicates = {
        name: sorted(set(paths))
        for name, paths in _module_names().items()
        if len(set(paths)) > 1
    }
    if not duplicates:
        return
    lines: list[str] = []
    for name, paths in sorted(duplicates.items()):
        lines.append(f"  {name}")
        lines.extend(f"      {path}" for path in paths)
    raise AssertionError(
        "The same top-level name is defined in more than one module:\n"
        + "\n".join(lines)
        + "\n\nHow to fix: decide which fault it is.  Same thing twice -> put "
        "it in one module both sides import (core/email_utils.py and "
        "core/ip_utils.py are that shape) and delete the copies.  Different "
        "things -> rename them apart, specifically enough that neither name "
        "invites the collision back (BAND_GAP and CHART_BAR_GAP, not BAR_GAP "
        "and BAR_GAP_2)."
    )


def _module_constants() -> dict[str, list[str]]:
    """``{value_key: ["relpath::NAME", ...]}`` over every module-level constant."""
    by_value: dict[str, list[str]] = defaultdict(list)
    for path in app_files():
        for node in _parse(path).body:
            targets: list[ast.Name]
            value: ast.expr | None
            if isinstance(node, ast.Assign):
                targets = [t for t in node.targets if isinstance(t, ast.Name)]
                value = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                targets = [node.target]
                value = node.value
            else:
                continue
            if value is None:
                continue
            key = _constant_value_key(value)
            if key is None:
                continue
            for target in targets:
                if not target.id.startswith("__"):
                    by_value[key].append(f"{_rel(path)}::{target.id}")
    return by_value


def test_no_duplicate_constant_values() -> None:
    """The same constant value is not defined in two modules.

    This catches what a duplicate-*name* check cannot: the same regex or set
    copy-pasted under two different names.  ``core.cross_refs`` and
    ``api.formatters`` each held their own tag-span pattern, already diverged
    by a capture group, with a comment in one saying the two had to agree.
    """
    duplicates = {
        key: sorted(set(sites))
        for key, sites in _module_constants().items()
        if len({site.split("::")[0] for site in sites}) > 1
    }
    if not duplicates:
        return
    lines: list[str] = []
    for key, sites in sorted(duplicates.items()):
        lines.append(f"  {key}")
        lines.extend(f"      {site}" for site in sites)
    raise AssertionError(
        "The same constant value is defined in more than one module:\n"
        + "\n".join(lines)
        + "\n\nHow to fix: pick the module both sides can import — the lower "
        "layer, or a new small module holding just this — define it once "
        "there, and import it from every other site.  Only when the match is "
        "a true coincidence (the same surface, two concepts that must be free "
        "to diverge) rename one so the two stop looking alike, and say why in "
        "a comment."
    )

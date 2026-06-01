#!/usr/bin/env python
"""Pre-commit launcher: run mypy under the project venv, wherever PATH points.

The mypy hook is ``language: system`` because the django-stubs plugin needs the
project's own deps, settings, and DATABASE_URL — none of which exist in
pre-commit's isolated per-hook virtualenvs.  But ``language: system`` runs
whatever ``python`` is first on PATH, so committing without the venv activated
(notably on Windows, where the App-execution-alias shim shadows it) fails with
"No module named mypy".

This launcher runs under *any* interpreter and re-dispatches to the venv's
python; it falls back to the current interpreter when no ``venv/`` is present
(e.g. CI that installed deps globally, or a developer who activated a venv in a
different location).  So it strictly improves the common case and never
regresses the others.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANDIDATES = (
    ROOT / "venv" / "Scripts" / "python.exe",  # Windows
    ROOT / "venv" / "bin" / "python",          # Linux/macOS
)
python = next((str(p) for p in CANDIDATES if p.exists()), sys.executable)
raise SystemExit(subprocess.call([python, "-m", "mypy", *sys.argv[1:]]))

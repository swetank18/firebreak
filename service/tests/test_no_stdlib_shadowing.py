"""No top-level package may shadow a stdlib module.

Cost us ~30 minutes at hour 5. A directory named `platform/` at the repo root
shadowed stdlib `platform`, which pandas, pytest and pyarrow all import — so
every tool worked from outside the repo and nothing worked from inside it. The
failure surfaced as a misleading `AttributeError: module 'platform' has no
attribute 'python_implementation'` during pip install.

Six agents were about to run in parallel against this layout.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

_IGNORED = {".git", ".venv", "node_modules", "__pycache__", "scenarios", "fixtures", "docs", "lanes"}


def test_no_top_level_package_shadows_stdlib():
    stdlib = set(sys.stdlib_module_names)
    offenders = [
        p.name
        for p in REPO.iterdir()
        if p.is_dir() and p.name not in _IGNORED and not p.name.startswith(".")
        and p.name in stdlib
    ]
    assert not offenders, (
        f"top-level dirs shadow stdlib modules: {offenders}. "
        "Anything importing them breaks only when run from the repo root."
    )


def test_stdlib_platform_resolves_to_stdlib():
    import platform

    assert "site-packages" not in platform.__file__
    assert str(REPO) not in platform.__file__
    assert hasattr(platform, "python_implementation")

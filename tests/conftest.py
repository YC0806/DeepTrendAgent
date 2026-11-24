from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _detect_package_dir(repo_root: Path) -> Path:
    for child in repo_root.iterdir():
        if not child.is_dir():
            continue
        if (
            (child / "__init__.py").is_file()
            and (child / "config.py").is_file()
            and (child / "models.py").is_file()
            and (child / "provider").is_dir()
            and (child / "tools").is_dir()
            and (child / "scripts").is_dir()
        ):
            return child
    raise RuntimeError("Could not detect the DeepTrend package directory.")


PACKAGE_DIR = _detect_package_dir(REPO_ROOT)

if PACKAGE_DIR.name != "deeptrend" and "deeptrend" not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        "deeptrend",
        PACKAGE_DIR / "__init__.py",
        submodule_search_locations=[str(PACKAGE_DIR)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not create a deeptrend alias for {PACKAGE_DIR}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["deeptrend"] = module
    spec.loader.exec_module(module)

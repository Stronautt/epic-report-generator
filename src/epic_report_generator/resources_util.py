"""Resolve paths to bundled resource files."""

from __future__ import annotations

import importlib.resources
from pathlib import Path


def get_resource_path(filename: str) -> Path:
    """Return the filesystem path to a file inside the ``resources`` package.

    Works with editable installs, standard wheels, and frozen binaries.

    Raises:
        FileNotFoundError: If *filename* does not exist in the resources
            package.
    """
    ref = importlib.resources.files("epic_report_generator.resources").joinpath(
        filename
    )
    # as_file() is needed when running from a zip/wheel; for normal installs
    # the traversable is already a concrete Path.
    path = Path(str(ref))
    if not path.is_file():
        raise FileNotFoundError(f"Resource not found: {filename}")
    return path

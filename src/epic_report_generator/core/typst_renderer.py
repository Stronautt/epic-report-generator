"""Compile the bundled Typst templates into PDF bytes.

The Typst Python binding has no in-memory virtual filesystem: relative
``import`` / ``json()`` references resolve against a real project root on disk.
So each render assembles a throwaway project directory — the bundled ``.typ``
templates plus the per-render ``data.json`` — and compiles ``main.typ`` against
it. Fonts are loaded from the bundled ``resources/fonts`` and system fonts are
ignored for deterministic output. Charts are drawn natively by the templates,
so there are no image assets to write.
"""

from __future__ import annotations

import importlib.resources as resources
import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

import typst

logger = logging.getLogger(__name__)

_RESOURCES = "epic_report_generator.resources"


def render_pdf(
    payload: dict[str, Any], extra_font_paths: list[str] | None = None
) -> bytes:
    """Render the report payload to PDF bytes via Typst.

    *extra_font_paths* are added to Typst's font search path so a custom report
    font (NFR-05) is available alongside the bundled Inter (Latin/Cyrillic/Greek
    fallback) and Noto Sans CJK JP (CJK ideograph/kana/Hangul fallback).
    """
    res = resources.files(_RESOURCES)
    with resources.as_file(res) as res_dir:
        templates_src = Path(res_dir) / "typst"
        fonts_dir = Path(res_dir) / "fonts"

        with tempfile.TemporaryDirectory(prefix="erg-typst-") as tmp:
            root = Path(tmp)
            # Bundled templates: theme.typ, main.typ, components/, pages/.
            shutil.copytree(templates_src, root, dirs_exist_ok=True)
            # Per-render view-model.
            (root / "data.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )

            font_paths = [str(fonts_dir)]
            font_paths.extend(p for p in (extra_font_paths or []) if p)

            pdf = typst.compile(
                input=str(root / "main.typ"),
                root=str(root),
                font_paths=font_paths,
                ignore_system_fonts=True,
            )

    if not isinstance(pdf, bytes):  # pragma: no cover - defensive
        raise RuntimeError(f"Typst returned {type(pdf)!r}, expected bytes")
    return pdf

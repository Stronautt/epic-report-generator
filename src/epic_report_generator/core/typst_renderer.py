"""Compile the bundled Typst templates into PDF bytes.

The Typst Python binding has no in-memory virtual filesystem: relative
``import`` / ``json()`` references resolve against a real project root on disk.
So each render assembles a throwaway project directory — the bundled ``.typ``
templates plus the per-render ``data.json`` — and compiles ``main.typ`` against
it. The bundled Inter is loaded from ``resources/fonts``; the large Noto Sans CJK
JP fallback lives in ``resources/fonts_cjk`` and is added to the font search path
only when the report text contains CJK. System fonts are ignored for
deterministic output. Charts are drawn natively by the templates, so there are no
image assets to write.
"""

from __future__ import annotations

import importlib.resources as resources
import json
import logging
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_RESOURCES = "epic_report_generator.resources"

# CJK ideographs, kana, Hangul, fullwidth forms, and astral CJK extensions. Used
# to gate inclusion of the bundled 16MB Noto Sans CJK JP font in Typst's font
# search path so pure-Latin reports never pay to scan it.
_CJK_RE = re.compile("[　-ヿ㐀-䶿一-鿿가-힯" "豈-﫿＀-￯\U00020000-\U0002ffff]")


def _needs_cjk(text: str) -> bool:
    """Return True if *text* contains CJK ideographs, kana, or Hangul.

    Scanning the serialized payload is a complete test: all user-facing report
    text is carried in the payload JSON.
    """
    return _CJK_RE.search(text) is not None


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
        fonts_cjk_dir = Path(res_dir) / "fonts_cjk"

        with tempfile.TemporaryDirectory(prefix="erg-typst-") as tmp:
            root = Path(tmp)
            # Bundled templates: theme.typ, main.typ, components/, pages/.
            shutil.copytree(templates_src, root, dirs_exist_ok=True)
            # Per-render view-model.
            data_json = json.dumps(payload, ensure_ascii=False)
            (root / "data.json").write_text(data_json, encoding="utf-8")

            # Base path holds Inter (Latin/Cyrillic/Greek). The 16MB Noto Sans
            # CJK JP lives in a sibling dir that is only searched when the report
            # actually contains CJK text — Typst scans every font in font_paths
            # per compile, so a pure-Latin render must never pay to scan it.
            font_paths = [str(fonts_dir)]
            if _needs_cjk(data_json):
                font_paths.append(str(fonts_cjk_dir))
            font_paths.extend(p for p in (extra_font_paths or []) if p)

            # Imported lazily so the native Typst compiler is loaded into the
            # process only when the first report is rendered, not at startup.
            import typst

            pdf = typst.compile(
                input=str(root / "main.typ"),
                root=str(root),
                font_paths=font_paths,
                ignore_system_fonts=True,
            )

    if not isinstance(pdf, bytes):  # pragma: no cover - defensive
        raise RuntimeError(f"Typst returned {type(pdf)!r}, expected bytes")
    return pdf

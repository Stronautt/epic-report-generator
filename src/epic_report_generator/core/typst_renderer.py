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


def icon_ext(data: bytes) -> str:
    """Pick the file extension matching *data*'s real image format.

    Jira issue-type ``iconUrl``s serve PNG as often as SVG, and Typst infers the
    decoder from the file extension — so PNG bytes written to a ``.svg`` file
    hard-error the whole compile. Sniff the magic bytes; fall back to ``svg`` for
    anything textual (the historical assumption). The view-model's icon path and
    the on-disk filename both route through here so they always agree.
    """
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] in (b"GIF8",):
        return "gif"
    return "svg"


def render_pdf(
    payload: dict[str, Any],
    extra_font_paths: list[str] | None = None,
    icons: dict[str, bytes] | None = None,
) -> bytes:
    """Render the report payload to PDF bytes via Typst.

    *extra_font_paths* are added to Typst's font search path so a custom report
    font (NFR-05) is available alongside the bundled Inter (Latin/Cyrillic/Greek
    fallback) and Noto Sans CJK JP (CJK ideograph/kana/Hangul fallback).

    *icons* maps issue-type id → icon bytes; each is written into the throwaway
    project as ``icons/<id>.<ext>`` (extension sniffed from the bytes via
    :func:`icon_ext`) so the templates can ``image()`` them (typst-py has no
    in-memory FS).  The view-model only emits an icon path for ids present here
    — routing the filename through the same :func:`icon_ext` — so a referenced
    file is always written first with a matching extension.
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

            # Issue-type icons referenced by the payload (custom-hierarchy only).
            if icons:
                icons_dir = root / "icons"
                icons_dir.mkdir(exist_ok=True)
                for type_id, data in icons.items():
                    (icons_dir / f"{type_id}.{icon_ext(data)}").write_bytes(data)

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

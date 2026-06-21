"""Rasterise the app logo from the Icon Composer ``.icon`` bundle.

The single source of truth for the app icon on every platform is the
``packaging/macos/logo.icon`` bundle (authored in Icon Composer). macOS
compiles it directly with ``actool`` and gets its HIG padding + gradient for
free. Windows, Linux and the in-app window / Help-panel logo instead need a
plain raster PNG, which this script produces by reproducing the bundle's look:
the ``fill`` gradient painted into a rounded-square (squircle) tile, with the
foreground layers (``Assets/*.svg``) composited on top — so the PNG carries the
**same background and shape** as the ``.icon`` macOS renders, rather than a bare
full-bleed cut-out.

It runs at build time (see ``.github/workflows/build.yml``) so no raster copies
of the logo are committed to the repo. Developers can regenerate the in-app
icon locally with::

    python packaging/render_logo.py \\
        --icon-dir packaging/macos/logo.icon \\
        --out src/epic_report_generator/resources/logo.png

Pass ``--no-background`` to fall back to the historical transparent full-bleed
cut-out (foreground layers only, no gradient tile).

Rendering uses PySide6's QtSvg (already a project dependency) so it needs no
extra native libraries and works headless on all three CI runners.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Qt must be able to start without a display on CI runners.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QBrush,
    QColor,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
)
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

# Apple Display-P3 (D65) linear → linear-sRGB (D65) matrix. Icon Composer writes
# fill colours as ``display-p3:`` floats, so they must be transformed into the
# sRGB space QColor works in or the tile reads noticeably greener/cooler.
_P3_TO_SRGB = (
    (1.2249401762805075, -0.2249404157777521, 0.0),
    (-0.0420569784699038, 1.0420569784699038, 0.0),
    (-0.0196375547479813, -0.0786360331158501, 1.0982735878638316),
)

# macOS app-icon corner radius as a fraction of the tile's side (the iOS/macOS
# "squircle" rounded-rect approximation), so the PNG takes the app-icon shape.
_RADIUS_RATIO = 0.2237


def _srgb_eotf(v: float) -> float:
    """Gamma-encoded sRGB/P3 channel value → linear light."""
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def _srgb_oetf(v: float) -> float:
    """Linear light → gamma-encoded sRGB channel value (clamped to [0, 1])."""
    v = min(max(v, 0.0), 1.0)
    return v * 12.92 if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055


def _parse_color(spec: str) -> QColor:
    """Parse an Icon Composer colour spec into an sRGB ``QColor``.

    Handles ``display-p3:r,g,b[,a]`` (converted to sRGB) and ``srgb:…`` /
    bare comma lists (treated as already sRGB). Values are floats in ``[0, 1]``.
    """
    space, _, body = spec.partition(":")
    parts = [float(x) for x in body.split(",") if x.strip()]
    r, g, b = parts[:3]
    a = parts[3] if len(parts) > 3 else 1.0
    if space == "display-p3":
        lin = [_srgb_eotf(c) for c in (r, g, b)]
        r, g, b = (
            _srgb_oetf(row[0] * lin[0] + row[1] * lin[1] + row[2] * lin[2])
            for row in _P3_TO_SRGB
        )
    return QColor.fromRgbF(
        min(max(r, 0.0), 1.0),
        min(max(g, 0.0), 1.0),
        min(max(b, 0.0), 1.0),
        min(max(a, 0.0), 1.0),
    )


def _fill_color(icon_dir: Path) -> QColor | None:
    """Return the ``.icon`` background fill colour, or ``None`` if absent."""
    data = json.loads((icon_dir / "icon.json").read_text(encoding="utf-8"))
    fill = data.get("fill")
    if not isinstance(fill, dict):
        return None
    spec = fill.get("automatic-gradient") or fill.get("solid")
    if not isinstance(spec, str):
        return None
    return _parse_color(spec)


def _lighten(color: QColor, amount: float) -> QColor:
    """Mix *color* toward white by *amount* (``0`` = unchanged, ``1`` = white)."""
    r, g, b, a = color.getRgb()
    return QColor(
        round(r + (255 - r) * amount),
        round(g + (255 - g) * amount),
        round(b + (255 - b) * amount),
        a,
    )


def _layer_files(icon_dir: Path) -> list[str]:
    """Return the layer SVG file names ordered bottom-to-top for compositing.

    Icon Composer's ``icon.json`` lists the *front-most* layer first, so the
    JSON order is reversed to paint back-to-front (e.g. the coloured objects
    first, then the trend arrow on top).
    """
    data = json.loads((icon_dir / "icon.json").read_text(encoding="utf-8"))
    names: list[str] = []
    for group in data.get("groups", []):
        for layer in group.get("layers", []):
            name = layer.get("image-name")
            if name:
                names.append(name)
    if not names:
        raise SystemExit(f"No layers found in {icon_dir / 'icon.json'}")
    names.reverse()
    return names


def render(
    icon_dir: Path,
    out: Path,
    size: int,
    pad: float,
    background: bool = True,
) -> None:
    """Composite the ``.icon`` into a square PNG at *out*.

    With *background* (the default) the bundle's ``fill`` gradient is painted
    into a rounded-square tile and the foreground layers go on top, reproducing
    the shape + background macOS renders from the same ``.icon``. With
    ``background=False`` only the foreground layers are drawn on a transparent
    canvas (the historical full-bleed cut-out).

    *pad* is the transparent margin around the tile as a fraction of *size*
    (``0`` = the tile fills the canvas).
    """
    # Held in a local so the QGuiApplication outlives the rendering.
    _app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])

    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

    margin = round(size * pad)
    target = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)

    base = _fill_color(icon_dir) if background else None
    if base is not None:
        # Reproduce Icon Composer's "automatic gradient": a subtle vertical
        # sheen, lighter at the top, settling to the fill colour at the bottom.
        gradient = QLinearGradient(target.topLeft(), target.bottomLeft())
        gradient.setColorAt(0.0, _lighten(base, 0.12))
        gradient.setColorAt(1.0, base)

        # fillPath gives an antialiased squircle tile (a clip path would leave
        # the rounded corners aliased on the raster engine).
        radius = target.width() * _RADIUS_RATIO
        tile = QPainterPath()
        tile.addRoundedRect(target, radius, radius)
        painter.fillPath(tile, QBrush(gradient))

    for name in _layer_files(icon_dir):
        svg = icon_dir / "Assets" / name
        renderer = QSvgRenderer(str(svg))
        if not renderer.isValid():
            painter.end()
            raise SystemExit(f"Could not load SVG layer: {svg}")
        renderer.render(painter, target)

    painter.end()

    out.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(out), "PNG"):
        raise SystemExit(f"Failed to write {out}")
    print(f"Wrote {out} ({size}x{size}, pad={pad}, background={background})")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--icon-dir",
        type=Path,
        required=True,
        help="Path to the .icon bundle (containing icon.json + Assets/).",
    )
    parser.add_argument(
        "--out", type=Path, required=True, help="Output PNG path."
    )
    parser.add_argument(
        "--size", type=int, default=1024, help="Square output size in pixels."
    )
    parser.add_argument(
        "--pad",
        type=float,
        default=0.0,
        help="Transparent margin around the tile as a fraction of size.",
    )
    parser.add_argument(
        "--no-background",
        dest="background",
        action="store_false",
        help="Draw only the foreground layers (transparent full-bleed cut-out, "
        "no gradient tile).",
    )
    args = parser.parse_args(argv)
    render(args.icon_dir, args.out, args.size, args.pad, args.background)


if __name__ == "__main__":
    main()

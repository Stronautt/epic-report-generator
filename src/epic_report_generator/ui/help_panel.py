"""User Guide panel — renders the bundled Markdown user guide.

The guide ships as a package resource (``resources/user-guide.md``). The body
is converted to HTML with Python-Markdown and rendered in a ``QTextBrowser``
styled by a theme-aware stylesheet, so tables, code blocks, callouts and
typography look polished rather than flat. (Qt's rich-text engine is used
rather than WebEngine, which the app deliberately excludes for bundle size, so
styling stays within its supported HTML/CSS subset.)

The guide opens with a centred raw-HTML banner (logo + title + tagline) that is
great on GitHub but not part of the body styling; it is lifted into native
widgets and the remainder is rendered as Markdown. If Python-Markdown is
unavailable for any reason, the panel falls back to Qt's built-in Markdown
importer so the guide still shows.
"""

from __future__ import annotations

import importlib.resources
import logging
import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QTextBrowser, QVBoxLayout, QWidget

from epic_report_generator.core import theming
from epic_report_generator.services.config_manager import ConfigManager

logger = logging.getLogger(__name__)

_GUIDE_FILE = "user-guide.md"
_LOGO_FILE = "logo.png"
_LOGO_HEIGHT = 64


# ── Resource loading ────────────────────────────────────────────────────────


def _read_resource_bytes(name: str) -> bytes | None:
    """Return the bytes of a bundled resource, or ``None`` if unavailable."""
    try:
        return (
            importlib.resources.files("epic_report_generator")
            .joinpath("resources", name)
            .read_bytes()
        )
    except (FileNotFoundError, OSError, ModuleNotFoundError) as exc:
        logger.warning("Could not load resource '%s': %s", name, exc)
        return None


def _read_guide() -> str:
    """Load the user guide Markdown, with a graceful fallback message."""
    data = _read_resource_bytes(_GUIDE_FILE)
    if data is None:
        return "# User Guide\n\nThe user guide could not be loaded."
    return data.decode("utf-8")


def _split_banner(md_text: str) -> tuple[str, str, str]:
    """Lift the leading HTML banner off the Markdown body.

    Returns ``(title, tagline, body)``. Title/tagline are pulled from the raw
    ``<h1>``/``<em>`` banner for a native header; every raw ``<p>``/``<h1>``
    block (header logo/title/tagline and the footer line) is stripped so the
    remainder is clean Markdown.
    """
    title = "User Guide"
    m = re.search(r"<h1[^>]*>(.*?)</h1>", md_text, re.DOTALL | re.IGNORECASE)
    if m:
        title = re.sub(r"<[^>]+>", "", m.group(1)).strip() or title

    tagline = ""
    m = re.search(r"<em>(.*?)</em>", md_text, re.DOTALL | re.IGNORECASE)
    if m:
        tagline = re.sub(r"<[^>]+>", "", m.group(1)).strip()

    body = re.sub(r"<p\b[^>]*>.*?</p>", "", md_text, flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r"<h1\b[^>]*>.*?</h1>", "", body, flags=re.DOTALL | re.IGNORECASE)
    return title, tagline, body.strip()


# ── Theme palette ───────────────────────────────────────────────────────────


def _colors(dark: bool, shades: dict[str, str] | None) -> dict[str, str]:
    """Colour tokens for the active theme.

    Neutral tokens (body text, headings ink, code surface) are fixed; the
    accent-family tokens (section headings, links, table header, code bar, zebra
    rows, callout) follow the configured accent via *shades* (from
    :func:`theming.qt_shades`). When no accent is set, *shades* is ``None`` and
    the stock blue is used so the default look is unchanged.
    """
    if dark:
        c = {
            "text": "#D7DCE3",
            "h1": "#F0F3F8",
            "h3": "#E1E6EE",
            "code_fg": "#E6EAF1",
        }
        stock_accent, stock_link = "#7AB4FF", "#5AA0FF"
        gray, neutral_soft = "#2C313A", "#1A2336"
    else:
        c = {
            "text": "#243047",
            "h1": "#0B1B33",
            "h3": "#243047",
            "code_fg": "#243047",
        }
        stock_accent, stock_link = "#0747A6", "#0052CC"
        gray, neutral_soft = "#ECEDF0", "#F1F5FB"

    # Zebra rows and inline-code pills use a neutral gray, independent of accent.
    c["row"] = gray
    if shades is not None:
        accent = shades["accent"]
        c.update(
            h2=accent,
            link=accent,
            th_fg=accent,
            code_bar=accent,
            accent=accent,
            soft_bg=shades["softer"],
        )
    else:
        c.update(
            h2=stock_accent,
            link=stock_link,
            th_fg=stock_accent,
            code_bar=stock_accent,
            accent=stock_accent,
            soft_bg=neutral_soft,
        )
    return c


def _stylesheet(c: dict[str, str], mono: str) -> str:
    """Build the QTextDocument default stylesheet from a colour palette.

    Flat by design — no outer table borders or grid lines. Tables use a header
    underline plus zebra rows (striping is baked into the HTML); code uses the
    real platform monospace family (*mono*) with no fill — block code keeps a
    left accent bar, inline code is bold; callouts use a subtle tint.
    """
    return f"""
        body {{ color: {c['text']}; font-size: 14px; line-height: 150%; }}
        h1 {{ color: {c['h1']}; font-size: 25px; margin: 20px 0 6px 0; }}
        h2 {{ color: {c['h2']}; font-size: 19px; margin: 26px 0 8px 0; }}
        h3 {{ color: {c['h3']}; font-size: 15px; margin: 18px 0 4px 0; }}
        p {{ color: {c['text']}; margin: 8px 0; }}
        a {{ color: {c['link']}; text-decoration: none; }}
        ul, ol {{ margin: 6px 0 6px 6px; }}
        li {{ color: {c['text']}; margin: 4px 0; }}
        code {{ background-color: {c['soft_bg']}; color: {c['code_fg']};
            font-weight: bold; font-family: "{mono}"; font-size: 13px;
            padding: 1px 4px; }}
        pre {{ color: {c['code_fg']};
            border-left: 4px solid {c['code_bar']};
            padding: 8px 14px; margin: 12px 0; }}
        pre, code {{ white-space: pre-wrap; font-family: "{mono}"; }}
        blockquote {{ background-color: {c['soft_bg']}; color: {c['text']};
            margin: 12px 0; padding: 8px 14px; }}
        table {{ border: none; margin: 14px 0; }}
        th {{ color: {c['th_fg']}; border-bottom: 2px solid {c['accent']};
            padding: 6px 12px 6px 10px; text-align: left; }}
        td {{ color: {c['text']}; padding: 7px 12px 7px 10px; }}
        hr {{ color: {c['row']}; }}
    """


# ── Markdown → HTML ─────────────────────────────────────────────────────────


def _github_slugify(value: str, separator: str) -> str:
    """GitHub-compatible heading slug so the in-page Contents links resolve."""
    value = value.strip().lower()
    value = re.sub(r"[^\w\s-]", "", value)
    return re.sub(r"\s", separator, value)


def _stripe_rows(html: str, row_color: str) -> str:
    """Tint every other body row of each table for readable zebra striping.

    Qt's rich text has no ``:nth-child``, so the colour is baked onto the cells
    of alternate ``<tbody>`` rows as a ``bgcolor`` attribute (which Qt honours).
    """

    def _stripe(match: re.Match[str]) -> str:
        segments = match.group(1).split("<tr>")
        out = [segments[0]]
        for i, seg in enumerate(segments[1:]):
            if i % 2 == 1:  # every second data row
                seg = re.sub(r"<td", f'<td bgcolor="{row_color}"', seg)
            out.append("<tr>" + seg)
        return "<tbody>" + "".join(out) + "</tbody>"

    return re.sub(r"<tbody>(.*?)</tbody>", _stripe, html, flags=re.DOTALL)


def _wrap_callouts(html: str, bg: str) -> str:
    """Render blockquote callouts as single-cell tables for real padding.

    Qt's rich text honours interior ``padding`` on table cells but not on block
    elements like ``<blockquote>``, so the tinted callout would otherwise have
    its text flush against the edges. A one-cell table gives proper inset.
    """

    def repl(match: re.Match[str]) -> str:
        inner = match.group(1).strip()
        return (
            '<table width="100%" cellspacing="0" cellpadding="11">'
            f'<tr><td bgcolor="{bg}">{inner}</td></tr></table>'
        )

    return re.sub(r"<blockquote>(.*?)</blockquote>", repl, html, flags=re.DOTALL)


_md_converter = None  # cached Python-Markdown instance (built once, reused)


def _markdown_converter():
    """Return a cached Python-Markdown converter, or ``None`` if unavailable.

    Extension instances are passed directly (rather than by name) to avoid
    entry-point discovery, which keeps frozen builds working.  The converter and
    its compiled extensions are built once and reused via ``reset()`` — rebuilding
    them on every theme toggle is needlessly expensive.
    """
    global _md_converter
    if _md_converter is not None:
        return _md_converter
    try:
        from markdown import Markdown
        from markdown.extensions.fenced_code import FencedCodeExtension
        from markdown.extensions.sane_lists import SaneListExtension
        from markdown.extensions.tables import TableExtension
        from markdown.extensions.toc import TocExtension
    except ImportError as exc:  # pragma: no cover - depends on env
        logger.warning("Python-Markdown unavailable, falling back: %s", exc)
        return None

    _md_converter = Markdown(
        extensions=[
            TableExtension(),
            FencedCodeExtension(),
            SaneListExtension(),
            TocExtension(slugify=_github_slugify),
        ],
        output_format="html",
    )
    return _md_converter


def _render_markdown(body_md: str, row_color: str, soft_color: str) -> str | None:
    """Convert Markdown to HTML, or ``None`` if Python-Markdown is unavailable."""
    md = _markdown_converter()
    if md is None:
        return None
    html = md.reset().convert(body_md)

    # Drop entirely-empty header rows (a "| | | |" layout table, like the
    # Contents grid, would otherwise render as a solid coloured bar).
    def _drop_empty_thead(match: re.Match[str]) -> str:
        return match.group(0) if re.sub(r"<[^>]+>", "", match.group(1)).strip() else ""

    html = re.sub(r"<thead>(.*?)</thead>", _drop_empty_thead, html, flags=re.DOTALL)

    # Qt's anchor navigation keys off <a name>, not id — mirror heading ids so
    # the Contents links scroll.
    html = re.sub(r'<h([1-6]) id="([^"]+)">', r'<h\1 id="\2"><a name="\2"></a>', html)

    # Full-width tables with zebra rows.
    html = html.replace("<table>", '<table width="100%" cellspacing="0">')
    html = _stripe_rows(html, row_color)

    # Unwrap <code> inside fenced <pre> so the block's fill/left-bar come from
    # <pre> alone (no doubled inline-code background).
    html = re.sub(r"<pre><code[^>]*>", "<pre>", html)
    html = html.replace("</code></pre>", "</pre>")

    # Inline code: Qt ignores horizontal padding on inline spans, so pad the
    # tinted pill with no-break spaces so the text has breathing room.
    html = re.sub(
        r"<code>(.*?)</code>",
        lambda m: f"<code> {m.group(1)} </code>",
        html,
        flags=re.DOTALL,
    )

    # Padded callouts (Qt ignores padding on <blockquote>).
    html = _wrap_callouts(html, soft_color)
    return html


# ── Panel ───────────────────────────────────────────────────────────────────


class HelpPanel(QWidget):
    """Sidebar panel that renders the bundled user guide as styled rich text."""

    def __init__(self, config: ConfigManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._dark = False
        title, tagline, self._body = _split_banner(_read_guide())
        self._build_ui(title, tagline)
        self._render()

    def _build_ui(self, title: str, tagline: str) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 16)
        root.setSpacing(8)

        logo_bytes = _read_resource_bytes(_LOGO_FILE)
        if logo_bytes:
            pixmap = QPixmap()
            if pixmap.loadFromData(logo_bytes):
                logo = QLabel()
                logo.setPixmap(
                    pixmap.scaledToHeight(
                        _LOGO_HEIGHT, Qt.TransformationMode.SmoothTransformation
                    )
                )
                logo.setAlignment(Qt.AlignmentFlag.AlignHCenter)
                root.addWidget(logo)

        heading = QLabel(title)
        heading.setProperty("heading", "true")
        heading.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        root.addWidget(heading)

        if tagline:
            sub = QLabel(tagline)
            sub.setProperty("subheading", "true")
            sub.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            sub.setWordWrap(True)
            root.addWidget(sub)

        self._view = QTextBrowser()
        self._view.setObjectName("guideView")
        self._view.setOpenExternalLinks(True)
        self._view.document().setDocumentMargin(4)
        # Drop the qt-material scroll-area frame so the guide sits directly on
        # the panel — no "page in a page" box.
        self._view.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(self._view, 1)

    def _render(self) -> None:
        """(Re)render the guide for the current theme + configured accent."""
        accent = self._config.get("accent_color", "")
        shades = (
            theming.qt_shades(accent, self._dark)
            if accent and theming.is_valid_hex(accent)
            else None
        )
        c = _colors(self._dark, shades)
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
        html = _render_markdown(self._body, c["row"], c["soft_bg"])
        # An explicit widget-level text colour overrides qt-material, which
        # otherwise paints the body in the (accent) primary colour.
        self._view.setStyleSheet(
            "QTextBrowser#guideView { border: none; background: transparent; "
            f"color: {c['text']}; }}"
        )
        if html is not None:
            self._view.document().setDefaultStyleSheet(_stylesheet(c, mono))
            self._view.setHtml(html)
        else:
            self._view.setMarkdown(self._body)

    def set_dark(self, dark: bool) -> None:
        """Re-render with the light/dark stylesheet after a theme switch."""
        self._dark = dark
        self._render()

"""App-specific QSS overlays applied on top of the qt-material base theme.

The base Material Design theme (light_blue / dark_blue) is applied via
``qt_material.apply_stylesheet`` in the main window.  These stylesheets
contain only app-specific overrides (object-name and property selectors)
that complement the material base.

Usage:  apply COMMON_THEME first, then ``light_theme()`` or ``dark_theme()``
on top.  All three are applied at the window level.

Accent colours are tokenised (``@ACCENT@``/``@SOFT@``/``@SOFTER@``/``@BORDER@``)
so a custom accent (NFR-05) can recolour the overlay.  ``light_theme()`` /
``dark_theme()`` substitute the tokens; called with no argument they use the
stock defaults derived from ``theming.qt_shades(DEFAULT_ACCENT, …)`` — the same
accent maths a custom accent goes through.
"""

from __future__ import annotations

from epic_report_generator.core import theming

# ---------------------------------------------------------------------------
# Shared structural rules — theme-independent (no color values)
# ---------------------------------------------------------------------------

COMMON_THEME = """
/* ── Sidebar nav buttons — layout/sizing ────────────────────────── */
#sidebar QPushButton {
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 10px 16px;
    text-align: left;
    font-size: 13px;
    font-weight: 500;
}
#sidebar QPushButton:checked {
    font-weight: 600;
}
#sidebar QPushButton:disabled {
    background: transparent;
}

/* ── Danger button — identical in both themes ────────────────────── */
QPushButton[danger="true"] {
    background-color: #e53935;
    color: white;
    border: none;
}
QPushButton[danger="true"]:hover {
    background-color: #ef5350;
}

/* ── Secondary button — layout ──────────────────────────────────── */
QPushButton[secondary="true"] {
    background-color: transparent;
}
QPushButton[secondary="true"]:disabled {
    background: transparent;
}

/* ── Primary CTA button — page-level action ─────────────────────── */
QPushButton[primary="true"] {
    border: none;
    border-radius: 6px;
    padding: 9px 22px;
    font-size: 13px;
    font-weight: 600;
    min-width: 150px;
}

/* ── Step action bar (sticky footer) — layout ───────────────────── */
#stepActionBar QLabel[actionHint="true"] {
    font-size: 12px;
    font-weight: 500;
}

/* ── Dialog action buttons (Save / Cancel) — modern layout ──────── */
QDialogButtonBox#dialogButtons {
    qproperty-centerButtons: false;
}
QDialogButtonBox#dialogButtons QPushButton {
    border-radius: 6px;
    padding: 5px 14px;
    font-size: 13px;
    font-weight: 600;
    min-width: 80px;
}
QPushButton[dialogPrimary="true"] {
    border: none;
}
/* Cancel — red outline, identical in both themes (rgba hover tints work
   on light and dark backgrounds alike, like the danger button). */
QPushButton[dialogCancel="true"] {
    background-color: transparent;
    border: 1px solid #e53935;
    color: #e53935;
}
QPushButton[dialogCancel="true"]:hover {
    background-color: rgba(229, 57, 53, 0.12);
}
QPushButton[dialogCancel="true"]:pressed {
    background-color: rgba(229, 57, 53, 0.22);
}
QPushButton[dialogCancel="true"]:disabled {
    border-color: #cccccc;
    color: #aaaaaa;
}

/* ── Labels — heading / subheading — sizing ─────────────────────── */
QLabel[heading="true"] {
    font-size: 20px;
    font-weight: 600;
}
QLabel[subheading="true"] {
    font-size: 11px;
}
QLabel[sectionTitle="true"] {
    font-size: 13px;
    font-weight: 600;
}
QLabel[hint="true"] {
    font-size: 10px;
}

/* ── Status indicator ───────────────────────────────────────────── */
QLabel[status="connected"] {
    font-weight: 600;
}

/* ── Guide step header — layout/sizing ──────────────────────────── */
#guideStepHeader {
    text-align: left;
    background: transparent;
    border: none;
    border-radius: 4px;
    padding: 8px 4px;
    font-weight: 600;
    font-size: 13px;
}
#guideStepHeader:checked,
#guideStepHeader:pressed {
    background: transparent;
}

/* ── Log filter buttons — layout/sizing ─────────────────────────── */
#logFilterBtn {
    background: transparent;
    border-radius: 12px;
    padding: 4px 12px;
    font-size: 11px;
    font-weight: 500;
    min-width: 56px;
}
#logFilterBtn:checked {
    border-color: transparent;
    color: #ffffff;
}

/* ── Collapsible — step header (top-level) — layout/sizing ──────── */
#collapsibleStepHeader {
    text-align: left;
    border: none;
    border-radius: 0;
    padding: 0;
    min-height: 38px;
}
#stepBadge {
    border-radius: 11px;
    font-size: 12px;
    font-weight: 700;
    padding: 0;
    margin: 0;
}
#stepTitle {
    font-size: 15px;
    font-weight: 700;
    background: transparent;
}

/* ── Collapsible — nested section header — layout/sizing ────────── */
#collapsibleHeader {
    text-align: left;
    background: transparent;
    border: none;
    border-radius: 0;
    padding: 0;
}
#collapsibleHeader:checked,
#collapsibleHeader:pressed {
    background: transparent;
}
#sectionLabel {
    font-size: 12px;
    font-weight: 600;
    background: transparent;
}
#collapsibleArrow {
    font-size: 10px;
    background: transparent;
}

/* ── Epic key chips — layout/sizing ─────────────────────────────── */
#epicKeyChip {
    border-radius: 12px;
    padding: 0;
    font-size: 12px;
}
#epicKeyChipClose {
    background: transparent;
    border: none;
    border-radius: 9px;
    font-size: 14px;
    font-weight: bold;
    padding: 0;
}

/* ── Epic key tag input container — layout/sizing ───────────────── */
#epicKeyTagInput {
    border-radius: 4px;
    min-height: 40px;
}

/* ── Profile bar — layout ───────────────────────────────────────── */
#profileBar {
    padding-bottom: 8px;
}

/* ── Sidebar user info — layout/sizing ──────────────────────────── */
#sidebarAvatar {
    border-radius: 16px;
    font-size: 13px;
    font-weight: 600;
}
#sidebarUserName {
    font-weight: 600;
    font-size: 12px;
    background: transparent;
}
#sidebarSiteName {
    font-size: 11px;
    background: transparent;
}
#sidebarAuthBadge {
    font-size: 10px;
    background: transparent;
    border: none;
}
#sidebarLogoutBtn {
    background: transparent;
    border: none;
    font-size: 11px;
    font-weight: 500;
    padding: 0;
    text-decoration: none;
}
#sidebarFooter {
    background: transparent;
}
#sidebarVersion {
    font-size: 12px;
    font-weight: 600;
    padding: 4px 10px 0 10px;
    background: transparent;
    qproperty-alignment: 'AlignCenter';
}
#sidebarCopyright {
    font-size: 10px;
    font-weight: 500;
    padding: 0 10px 0 10px;
    background: transparent;
    qproperty-alignment: 'AlignCenter';
}
/* Update CTA — a blinking hyperlink (QLabel rich text) shown only when a newer
   release exists. Same font size as the version label above it; the accent
   colour and underline come from the inline <a> style (an anchor's colour is
   not stylable via QSS), so only structural rules live here. */
#sidebarUpdateLink {
    font-size: 12px;
    font-weight: 600;
    padding: 2px 10px 0 10px;
    background: transparent;
    qproperty-alignment: 'AlignCenter';
}
"""

# ---------------------------------------------------------------------------
# Light theme overlay — color overrides only (accent tokenised)
# ---------------------------------------------------------------------------

_LIGHT_TEMPLATE = """
/* ── Sidebar ─────────────────────────────────────────────────────── */
#sidebar {
    background-color: #e8eaf0;
    border-right: 1px solid #d0d4dc;
}
#sidebar QPushButton {
    color: #555555;
}
#sidebar QPushButton:hover {
    background-color: #dcdfe5;
}
#sidebar QPushButton:checked {
    background-color: @SOFT@;
    color: @ACCENT@;
}
#sidebar QPushButton:disabled {
    color: #aaaaaa;
}

/* ── Buttons — property variants ────────────────────────────────── */
QPushButton[secondary="true"] {
    color: @ACCENT@;
    border: 1px solid @ACCENT@;
}
QPushButton[secondary="true"]:hover {
    background-color: @SOFTER@;
}
QPushButton[secondary="true"]:disabled {
    color: #aaaaaa;
    border-color: #cccccc;
}

/* ── Dialog primary + Primary CTA — filled accent (shared states) ── */
@PRIMARY_BTN_STATES@
QPushButton[dialogPrimary="true"]:disabled {
    background-color: #cfd4dc;
    color: #ffffff;
}
QPushButton[primary="true"]:disabled {
    background-color: #cfd4dc;
    color: #ffffff;
}
#stepActionBar {
    background-color: #f0f2f6;
    border-top: 1px solid #d0d4dc;
}
#stepActionBar QLabel[actionHint="true"] {
    color: #555555;
}

/* ── Labels — heading / subheading ──────────────────────────────── */
QLabel[heading="true"] {
    color: #212121;
}
QLabel[subheading="true"] {
    color: #757575;
}
QLabel[sectionTitle="true"] {
    color: #424242;
}
QLabel[hint="true"] {
    color: #9e9e9e;
}

/* ── Status indicator ───────────────────────────────────────────── */
QLabel[status="connected"] {
    color: #43a047;
}
QLabel[status="disconnected"] {
    color: #e53935;
}

/* ── Guide step header ──────────────────────────────────────────── */
#guideStepHeader {
    color: #212121;
}
#guideStepHeader:checked,
#guideStepHeader:pressed {
    color: #212121;
}
#guideStepHeader:hover {
    background-color: #e0e0e0;
    color: #212121;
}

/* ── Log filter buttons ─────────────────────────────────────────── */
#logFilterBtn {
    border: 1px solid #d0d4dc;
    color: #757575;
}
#logFilterBtn:hover {
    background: #e0e0e0;
}
#logFilterBtn[level="debug"]:checked {
    background: #90a4ae;
}
#logFilterBtn[level="info"]:checked {
    background: @ACCENT@;
}
#logFilterBtn[level="warning"]:checked {
    background: #ff8f00;
}
#logFilterBtn[level="error"]:checked {
    background: #e53935;
}

/* ── Collapsible — step header (top-level) ──────────────────────── */
#collapsibleStepHeader {
    background-color: @SOFTER@;
    border-left: 3px solid @ACCENT@;
}
#collapsibleStepHeader:checked {
    background-color: @SOFTER@;
}
#collapsibleStepHeader:hover {
    background-color: @SOFT@;
}
#stepBadge {
    background-color: @ACCENT@;
    color: @ACCENT_ON@;
}
#stepTitle {
    color: #1a1d21;
}
#collapsibleStepHeader QLabel#collapsibleArrow {
    color: @ACCENT@;
}

/* ── Collapsible — nested section header ────────────────────────── */
#collapsibleHeader {
    border-bottom: 1px solid #e2e5ea;
    border-left: 2px solid #d7dbe2;
}
#collapsibleHeader:hover {
    background-color: #ededf0;
}
#nestedBody {
    border-left: 2px solid #d7dbe2;
}
#sectionLabel {
    color: #5a6068;
}
#collapsibleHeader QLabel#collapsibleArrow {
    color: #9aa0a6;
}

/* ── Epic key chips ─────────────────────────────────────────────── */
#epicKeyChip {
    background-color: @SOFTER@;
    border: 1px solid @BORDER@;
    color: @ACCENT@;
}
#epicKeyChipClose {
    color: @ACCENT@;
}
#epicKeyChipClose:hover {
    background-color: @BORDER@;
}

/* ── Epic key tag input container ───────────────────────────────── */
#epicKeyTagInput {
    border: 1px solid #d0d4dc;
    background: #fafafa;
}

/* ── Profile bar ────────────────────────────────────────────────── */
#profileBar {
    border-bottom: 1px solid #d0d4dc;
}

/* ── Sidebar user info ──────────────────────────────────────────── */
#sidebarUserInfo {
    border-top: 1px solid #d0d4dc;
}
#sidebarAvatar {
    background: @SOFT@;
    color: @ACCENT@;
}
#sidebarUserName {
    color: #212121;
}
#sidebarSiteName {
    color: #757575;
}
#sidebarAuthBadge {
    color: #757575;
}
#sidebarLogoutBtn {
    color: #757575;
}
#sidebarLogoutBtn:hover {
    color: #e53935;
}
#sidebarVersion {
    color: #8a8d94;
}
#sidebarCopyright {
    color: #aeb1b8;
}
"""

# ---------------------------------------------------------------------------
# Dark theme overlay — color overrides only (accent tokenised)
# ---------------------------------------------------------------------------

_DARK_TEMPLATE = """
/* ── Sidebar ─────────────────────────────────────────────────────── */
#sidebar {
    background-color: #1a1d21;
    border-right: 1px solid #2c2f33;
}
#sidebar QPushButton {
    color: #9e9e9e;
}
#sidebar QPushButton:hover {
    background-color: #2c2f33;
}
#sidebar QPushButton:checked {
    background-color: @SOFT@;
    color: @ACCENT@;
}
#sidebar QPushButton:disabled {
    color: #555555;
}

/* ── Buttons — property variants ────────────────────────────────── */
QPushButton[secondary="true"] {
    color: @ACCENT@;
    border: 1px solid @ACCENT@;
}
QPushButton[secondary="true"]:hover {
    background-color: @SOFT@;
}
QPushButton[secondary="true"]:disabled {
    color: #555555;
    border-color: #444444;
}

/* ── Dialog primary + Primary CTA — filled accent (shared states) ── */
@PRIMARY_BTN_STATES@
QPushButton[dialogPrimary="true"]:disabled {
    background-color: #3a3d41;
    color: #777777;
}
QPushButton[primary="true"]:disabled {
    background-color: #3a3d41;
    color: #777777;
}
#stepActionBar {
    background-color: #16181c;
    border-top: 1px solid #2c2f33;
}
#stepActionBar QLabel[actionHint="true"] {
    color: #b0b3b8;
}

/* ── Labels — heading / subheading ──────────────────────────────── */
QLabel[subheading="true"] {
    color: #9e9e9e;
}
QLabel[sectionTitle="true"] {
    color: #e0e0e0;
}
QLabel[hint="true"] {
    color: #757575;
}

/* ── Status indicator ───────────────────────────────────────────── */
QLabel[status="connected"] {
    color: #66bb6a;
}
QLabel[status="disconnected"] {
    color: #ef5350;
}

/* ── Guide step header ──────────────────────────────────────────── */
#guideStepHeader {
    color: #ffffff;
}
#guideStepHeader:checked,
#guideStepHeader:pressed {
    color: #ffffff;
}
#guideStepHeader:hover {
    background-color: #3a3d41;
    color: #ffffff;
}

/* ── Log filter buttons ─────────────────────────────────────────── */
#logFilterBtn {
    border: 1px solid #3a3d41;
    color: #9e9e9e;
}
#logFilterBtn:hover {
    background: #3a3d41;
}
#logFilterBtn[level="debug"]:checked {
    background: #78909c;
}
#logFilterBtn[level="info"]:checked {
    background: @ACCENT@;
}
#logFilterBtn[level="warning"]:checked {
    background: #ffab00;
    color: #212121;
}
#logFilterBtn[level="error"]:checked {
    background: #ef5350;
}

/* ── Collapsible — step header (top-level) ──────────────────────── */
#collapsibleStepHeader {
    background-color: @SOFT@;
    border-left: 3px solid @ACCENT@;
}
#collapsibleStepHeader:checked {
    background-color: @SOFT@;
}
#collapsibleStepHeader:hover {
    background-color: @BORDER@;
}
#stepBadge {
    background-color: @ACCENT@;
    color: @ACCENT_ON@;
}
#stepTitle {
    color: #f2f4f7;
}
#collapsibleStepHeader QLabel#collapsibleArrow {
    color: @ACCENT@;
}

/* ── Collapsible — nested section header ────────────────────────── */
#collapsibleHeader {
    border-bottom: 1px solid #2c2f33;
    border-left: 2px solid #34383d;
}
#collapsibleHeader:hover {
    background-color: #2c2f33;
}
#nestedBody {
    border-left: 2px solid #34383d;
}
#sectionLabel {
    color: #9aa0a6;
}
#collapsibleHeader QLabel#collapsibleArrow {
    color: #7f868d;
}

/* ── Epic key chips ─────────────────────────────────────────────── */
#epicKeyChip {
    background-color: @SOFT@;
    border: 1px solid @BORDER@;
    color: @ACCENT@;
}
#epicKeyChipClose {
    color: @ACCENT@;
}
#epicKeyChipClose:hover {
    background-color: @BORDER@;
}

/* ── Epic key tag input container ───────────────────────────────── */
#epicKeyTagInput {
    border: 1px solid #3a3d41;
    background: #1a1d21;
}

/* ── Profile bar ────────────────────────────────────────────────── */
#profileBar {
    border-bottom: 1px solid #3a3d41;
}

/* ── Sidebar user info ──────────────────────────────────────────── */
#sidebarUserInfo {
    border-top: 1px solid #3a3d41;
}
#sidebarAvatar {
    background: @SOFT@;
    color: @ACCENT@;
}
#sidebarSiteName {
    color: #9e9e9e;
}
#sidebarAuthBadge {
    color: #9e9e9e;
}
#sidebarLogoutBtn {
    color: #9e9e9e;
}
#sidebarLogoutBtn:hover {
    color: #ef5350;
}
#sidebarVersion {
    color: #8b8e92;
}
#sidebarCopyright {
    color: #65686c;
}
"""

# Stock overlay shades derived from the single accent-maths source, so the
# default look and a custom accent always go through the same algorithm.
_LIGHT_DEFAULT_SHADES = theming.qt_shades(theming.DEFAULT_ACCENT, dark=False)
_DARK_DEFAULT_SHADES = theming.qt_shades(theming.DEFAULT_ACCENT, dark=True)


# Shared filled-accent button states (dialogPrimary + primary CTA). Identical
# across light/dark; only the :disabled rule differs, so it stays per-template.
# Injected by ``_render`` via the ``@PRIMARY_BTN_STATES@`` placeholder before the
# accent tokens it contains are substituted.
_PRIMARY_BUTTON_STATES = """
QPushButton[dialogPrimary="true"] {
    background-color: @ACCENT@;
    color: @ACCENT_ON@;
}
QPushButton[dialogPrimary="true"]:hover {
    background-color: @ACCENT_HOVER@;
}
QPushButton[dialogPrimary="true"]:pressed {
    background-color: @ACCENT_PRESSED@;
}
QPushButton[primary="true"] {
    background-color: @ACCENT@;
    color: @ACCENT_ON@;
}
QPushButton[primary="true"]:hover {
    background-color: @ACCENT_HOVER@;
}
QPushButton[primary="true"]:pressed {
    background-color: @ACCENT_PRESSED@;
}
"""


def _render(template: str, shades: dict[str, str]) -> str:
    """Substitute accent tokens in *template* with *shades* hex values.

    ``@SOFTER@`` is replaced before ``@SOFT@`` because the latter is a prefix
    of the former; the ``@ACCENT_*@`` tokens are replaced before ``@ACCENT@``
    for the same reason.  ``@PRIMARY_BTN_STATES@`` is expanded first so the
    accent tokens inside the shared fragment are then substituted in turn.
    """
    accent = shades["accent"]
    return (
        template.replace("@PRIMARY_BTN_STATES@", _PRIMARY_BUTTON_STATES)
        .replace("@ACCENT_HOVER@", shades.get("accent_hover", accent))
        .replace("@ACCENT_PRESSED@", shades.get("accent_pressed", accent))
        .replace("@ACCENT_ON@", shades.get("accent_on", "#ffffff"))
        .replace("@ACCENT@", accent)
        .replace("@SOFTER@", shades["softer"])
        .replace("@SOFT@", shades["soft"])
        .replace("@BORDER@", shades["border"])
    )


def light_theme(shades: dict[str, str] | None = None) -> str:
    """Render the light overlay; *shades* ``None`` uses the stock blue."""
    return _render(_LIGHT_TEMPLATE, shades or _LIGHT_DEFAULT_SHADES)


def dark_theme(shades: dict[str, str] | None = None) -> str:
    """Render the dark overlay; *shades* ``None`` uses the stock blue."""
    return _render(_DARK_TEMPLATE, shades or _DARK_DEFAULT_SHADES)

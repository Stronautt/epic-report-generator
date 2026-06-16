"""App-specific QSS overlays applied on top of the qt-material base theme.

The base Material Design theme (light_blue / dark_blue) is applied via
``qt_material.apply_stylesheet`` in the main window.  These stylesheets
contain only app-specific overrides (object-name and property selectors)
that complement the material base.

Usage:  apply COMMON_THEME first, then the appropriate LIGHT_THEME or
DARK_THEME on top.  All three are applied at the window level.
"""

from __future__ import annotations

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

/* ── Collapsible section header — layout/sizing ─────────────────── */
#collapsibleHeader {
    text-align: left;
    background: transparent;
    border: none;
    border-radius: 0;
    padding: 10px 4px;
    font-weight: 600;
    font-size: 14px;
}
#collapsibleHeader:checked,
#collapsibleHeader:pressed {
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
"""

# ---------------------------------------------------------------------------
# Light theme overlay — color overrides only
# ---------------------------------------------------------------------------

LIGHT_THEME = """
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
    background-color: #d4e4ff;
    color: #2979ff;
}
#sidebar QPushButton:disabled {
    color: #aaaaaa;
}

/* ── Buttons — property variants ────────────────────────────────── */
QPushButton[secondary="true"] {
    color: #2979ff;
    border: 1px solid #2979ff;
}
QPushButton[secondary="true"]:hover {
    background-color: #e3f0ff;
}
QPushButton[secondary="true"]:disabled {
    color: #aaaaaa;
    border-color: #cccccc;
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
    background: #2979ff;
}
#logFilterBtn[level="warning"]:checked {
    background: #ff8f00;
}
#logFilterBtn[level="error"]:checked {
    background: #e53935;
}

/* ── Collapsible section header ─────────────────────────────────── */
#collapsibleHeader {
    border-bottom: 1px solid #d0d4dc;
    color: #212121;
}
#collapsibleHeader:checked,
#collapsibleHeader:pressed {
    color: #212121;
}
#collapsibleHeader:hover {
    background-color: #e0e0e0;
    color: #212121;
}

/* ── Epic key chips ─────────────────────────────────────────────── */
#epicKeyChip {
    background-color: #e3f0ff;
    border: 1px solid #b3d4ff;
    color: #2979ff;
}
#epicKeyChipClose {
    color: #2979ff;
}
#epicKeyChipClose:hover {
    background-color: #b3d4ff;
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
    background: #d4e4ff;
    color: #2979ff;
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
"""

# ---------------------------------------------------------------------------
# Dark theme overlay — color overrides only
# ---------------------------------------------------------------------------

DARK_THEME = """
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
    background-color: #1a2744;
    color: #448aff;
}
#sidebar QPushButton:disabled {
    color: #555555;
}

/* ── Buttons — property variants ────────────────────────────────── */
QPushButton[secondary="true"] {
    color: #448aff;
    border: 1px solid #448aff;
}
QPushButton[secondary="true"]:hover {
    background-color: #1a2744;
}
QPushButton[secondary="true"]:disabled {
    color: #555555;
    border-color: #444444;
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
    background: #448aff;
}
#logFilterBtn[level="warning"]:checked {
    background: #ffab00;
    color: #212121;
}
#logFilterBtn[level="error"]:checked {
    background: #ef5350;
}

/* ── Collapsible section header ─────────────────────────────────── */
#collapsibleHeader {
    border-bottom: 1px solid #3a3d41;
    color: #ffffff;
}
#collapsibleHeader:checked,
#collapsibleHeader:pressed {
    color: #ffffff;
}
#collapsibleHeader:hover {
    background-color: #3a3d41;
    color: #ffffff;
}

/* ── Epic key chips ─────────────────────────────────────────────── */
#epicKeyChip {
    background-color: #1a2744;
    border: 1px solid #1e3a5f;
    color: #448aff;
}
#epicKeyChipClose {
    color: #448aff;
}
#epicKeyChipClose:hover {
    background-color: #1e3a5f;
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
    background: #1a2744;
    color: #448aff;
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
"""

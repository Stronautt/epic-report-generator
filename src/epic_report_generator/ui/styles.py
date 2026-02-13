"""QSS stylesheets for light and dark themes."""

from __future__ import annotations

LIGHT_THEME = """
QMainWindow, QWidget {
    background-color: #FFFFFF;
    color: #172B4D;
    font-family: "Segoe UI", "SF Pro Display", "Helvetica Neue", sans-serif;
    font-size: 13px;
}

/* Sidebar */
#sidebar {
    background-color: #F4F5F7;
    border-right: 1px solid #DFE1E6;
}
#sidebar QPushButton {
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 10px 16px;
    text-align: left;
    color: #505F79;
    font-size: 13px;
}
#sidebar QPushButton:hover {
    background-color: #EBECF0;
}
#sidebar QPushButton:checked {
    background-color: #DEEBFF;
    color: #0052CC;
    font-weight: 600;
}

/* Buttons */
QPushButton {
    background-color: #0052CC;
    color: white;
    border: none;
    border-radius: 4px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #0065FF;
}
QPushButton:pressed {
    background-color: #0747A6;
}
QPushButton:disabled {
    background-color: #F4F5F7;
    color: #A5ADBA;
}
QPushButton[secondary="true"] {
    background-color: transparent;
    color: #0052CC;
    border: 1px solid #0052CC;
}
QPushButton[secondary="true"]:hover {
    background-color: #DEEBFF;
}
QPushButton[danger="true"] {
    background-color: #DE350B;
}
QPushButton[danger="true"]:hover {
    background-color: #FF5630;
}

/* Inputs */
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {
    border: 1px solid #DFE1E6;
    border-radius: 4px;
    padding: 6px 10px;
    background: #FAFBFC;
    color: #172B4D;
    font-size: 13px;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border-color: #4C9AFF;
    background: #FFFFFF;
}

/* Labels */
QLabel {
    color: #172B4D;
}
QLabel[heading="true"] {
    font-size: 20px;
    font-weight: 600;
    color: #172B4D;
}
QLabel[subheading="true"] {
    font-size: 11px;
    color: #6B778C;
}

/* Checkbox */
QCheckBox {
    spacing: 8px;
    color: #172B4D;
}

/* Progress bar */
QProgressBar {
    border: none;
    border-radius: 4px;
    background: #DFE1E6;
    text-align: center;
    height: 8px;
    color: transparent;
}
QProgressBar::chunk {
    background: #0052CC;
    border-radius: 4px;
}

/* Scroll area */
QScrollArea {
    border: none;
}

/* Tab widget */
QTabWidget::pane {
    border: none;
    background: transparent;
}
QTabBar::tab {
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 8px 20px;
    color: #505F79;
    font-size: 13px;
    font-weight: 500;
}
QTabBar::tab:hover {
    color: #172B4D;
    border-bottom-color: #DFE1E6;
}
QTabBar::tab:selected {
    color: #0052CC;
    border-bottom-color: #0052CC;
    font-weight: 600;
}

/* Group box */
QGroupBox {
    font-weight: 600;
    border: 1px solid #DFE1E6;
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 16px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #172B4D;
}

/* Date edit */
QDateEdit {
    border: 1px solid #DFE1E6;
    border-radius: 4px;
    padding: 6px 10px;
    background: #FAFBFC;
}

/* Guide step header */
#guideStepHeader {
    text-align: left;
    background: transparent;
    border: none;
    border-radius: 4px;
    padding: 8px 4px;
    font-weight: 600;
    font-size: 13px;
    color: #172B4D;
}
#guideStepHeader:hover {
    background-color: #EBECF0;
}

/* Log filter buttons */
#logFilterBtn {
    background: transparent;
    border: 1px solid #DFE1E6;
    border-radius: 12px;
    padding: 4px 12px;
    font-size: 11px;
    font-weight: 500;
    color: #6B778C;
    min-width: 56px;
}
#logFilterBtn:hover {
    background: #EBECF0;
}
#logFilterBtn:checked {
    border-color: transparent;
    color: #FFFFFF;
}
#logFilterBtn[level="debug"]:checked {
    background: #8C9CB8;
}
#logFilterBtn[level="info"]:checked {
    background: #0052CC;
}
#logFilterBtn[level="warning"]:checked {
    background: #FF8B00;
}
#logFilterBtn[level="error"]:checked {
    background: #DE350B;
}

/* Status indicator */
QLabel[status="connected"] {
    color: #36B37E;
    font-weight: 600;
}
QLabel[status="disconnected"] {
    color: #DE350B;
}

/* Collapsible section header */
#collapsibleHeader {
    text-align: left;
    background: transparent;
    border: none;
    border-bottom: 1px solid #DFE1E6;
    border-radius: 0;
    padding: 10px 4px;
    font-weight: 600;
    font-size: 14px;
    color: #172B4D;
}
#collapsibleHeader:hover {
    background-color: #EBECF0;
}

/* Epic key chip */
#epicKeyChip {
    background-color: #DEEBFF;
    border: 1px solid #B3D4FF;
    border-radius: 12px;
    padding: 0;
    color: #0052CC;
    font-size: 12px;
}
#epicKeyChipClose {
    background: transparent;
    border: none;
    border-radius: 9px;
    color: #0052CC;
    font-size: 14px;
    font-weight: bold;
    padding: 0;
}
#epicKeyChipClose:hover {
    background-color: #B3D4FF;
}

/* Epic key tag input container */
#epicKeyTagInput {
    border: 1px solid #DFE1E6;
    border-radius: 4px;
    background: #FAFBFC;
    min-height: 40px;
}
#epicKeyTagInput:focus-within {
    border-color: #4C9AFF;
    background: #FFFFFF;
}

/* Sidebar user info */
#sidebarUserInfo {
    border-top: 1px solid #DFE1E6;
}
#sidebarAvatar {
    background: #DEEBFF;
    border-radius: 16px;
    font-size: 13px;
    font-weight: 600;
    color: #0052CC;
}
#sidebarUserName {
    font-weight: 600;
    font-size: 12px;
    color: #172B4D;
    background: transparent;
}
#sidebarSiteName {
    font-size: 11px;
    color: #6B778C;
    background: transparent;
}
#sidebarAuthBadge {
    font-size: 10px;
    color: #6B778C;
    background: transparent;
    border: none;
}
#sidebarLogoutBtn {
    background: transparent;
    border: none;
    color: #6B778C;
    font-size: 11px;
    font-weight: 500;
    padding: 0;
    text-decoration: none;
}
#sidebarLogoutBtn:hover {
    color: #DE350B;
}
"""

DARK_THEME = """
QMainWindow, QWidget {
    background-color: #1B2638;
    color: #B8C7E0;
    font-family: "Segoe UI", "SF Pro Display", "Helvetica Neue", sans-serif;
    font-size: 13px;
}

#sidebar {
    background-color: #0D1424;
    border-right: 1px solid #1B2638;
}
#sidebar QPushButton {
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 10px 16px;
    text-align: left;
    color: #8C9CB8;
    font-size: 13px;
}
#sidebar QPushButton:hover {
    background-color: #1B2638;
}
#sidebar QPushButton:checked {
    background-color: #0D2137;
    color: #4C9AFF;
    font-weight: 600;
}

QPushButton {
    background-color: #0052CC;
    color: white;
    border: none;
    border-radius: 4px;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #0065FF;
}
QPushButton:pressed {
    background-color: #0747A6;
}
QPushButton:disabled {
    background-color: #1B2638;
    color: #505F79;
}
QPushButton[secondary="true"] {
    background-color: transparent;
    color: #4C9AFF;
    border: 1px solid #4C9AFF;
}
QPushButton[danger="true"] {
    background-color: #DE350B;
}

QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {
    border: 1px solid #2C3E5D;
    border-radius: 4px;
    padding: 6px 10px;
    background: #0D1424;
    color: #B8C7E0;
    font-size: 13px;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border-color: #4C9AFF;
}

QLabel {
    color: #B8C7E0;
}
QLabel[heading="true"] {
    font-size: 20px;
    font-weight: 600;
}
QLabel[subheading="true"] {
    font-size: 11px;
    color: #8C9CB8;
}

QCheckBox {
    spacing: 8px;
    color: #B8C7E0;
}

QProgressBar {
    border: none;
    border-radius: 4px;
    background: #2C3E5D;
    text-align: center;
    height: 8px;
    color: transparent;
}
QProgressBar::chunk {
    background: #4C9AFF;
    border-radius: 4px;
}

QScrollArea {
    border: none;
}

/* Tab widget */
QTabWidget::pane {
    border: none;
    background: transparent;
}
QTabBar::tab {
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 8px 20px;
    color: #8C9CB8;
    font-size: 13px;
    font-weight: 500;
}
QTabBar::tab:hover {
    color: #B8C7E0;
    border-bottom-color: #2C3E5D;
}
QTabBar::tab:selected {
    color: #4C9AFF;
    border-bottom-color: #4C9AFF;
    font-weight: 600;
}

QGroupBox {
    font-weight: 600;
    border: 1px solid #2C3E5D;
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 16px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #B8C7E0;
}

QDateEdit {
    border: 1px solid #2C3E5D;
    border-radius: 4px;
    padding: 6px 10px;
    background: #0D1424;
}

#guideStepHeader {
    text-align: left;
    background: transparent;
    border: none;
    border-radius: 4px;
    padding: 8px 4px;
    font-weight: 600;
    font-size: 13px;
    color: #B8C7E0;
}
#guideStepHeader:hover {
    background-color: #2C3E5D;
}

/* Log filter buttons */
#logFilterBtn {
    background: transparent;
    border: 1px solid #2C3E5D;
    border-radius: 12px;
    padding: 4px 12px;
    font-size: 11px;
    font-weight: 500;
    color: #8C9CB8;
    min-width: 56px;
}
#logFilterBtn:hover {
    background: #2C3E5D;
}
#logFilterBtn:checked {
    border-color: transparent;
    color: #FFFFFF;
}
#logFilterBtn[level="debug"]:checked {
    background: #6B778C;
}
#logFilterBtn[level="info"]:checked {
    background: #0052CC;
}
#logFilterBtn[level="warning"]:checked {
    background: #FFAB00;
    color: #172B4D;
}
#logFilterBtn[level="error"]:checked {
    background: #FF5630;
}

QLabel[status="connected"] {
    color: #36B37E;
    font-weight: 600;
}
QLabel[status="disconnected"] {
    color: #FF5630;
}

/* Collapsible section header */
#collapsibleHeader {
    text-align: left;
    background: transparent;
    border: none;
    border-bottom: 1px solid #2C3E5D;
    border-radius: 0;
    padding: 10px 4px;
    font-weight: 600;
    font-size: 14px;
    color: #B8C7E0;
}
#collapsibleHeader:hover {
    background-color: #2C3E5D;
}

/* Epic key chip */
#epicKeyChip {
    background-color: #0D2137;
    border: 1px solid #0747A6;
    border-radius: 12px;
    padding: 0;
    color: #4C9AFF;
    font-size: 12px;
}
#epicKeyChipClose {
    background: transparent;
    border: none;
    border-radius: 9px;
    color: #4C9AFF;
    font-size: 14px;
    font-weight: bold;
    padding: 0;
}
#epicKeyChipClose:hover {
    background-color: #0747A6;
}

/* Epic key tag input container */
#epicKeyTagInput {
    border: 1px solid #2C3E5D;
    border-radius: 4px;
    background: #0D1424;
    min-height: 40px;
}

/* Sidebar user info */
#sidebarUserInfo {
    border-top: 1px solid #2C3E5D;
}
#sidebarAvatar {
    background: #0D2137;
    border-radius: 16px;
    font-size: 13px;
    font-weight: 600;
    color: #4C9AFF;
}
#sidebarUserName {
    font-weight: 600;
    font-size: 12px;
    color: #B8C7E0;
    background: transparent;
}
#sidebarSiteName {
    font-size: 11px;
    color: #8C9CB8;
    background: transparent;
}
#sidebarAuthBadge {
    font-size: 10px;
    color: #8C9CB8;
    background: transparent;
    border: none;
}
#sidebarLogoutBtn {
    background: transparent;
    border: none;
    color: #8C9CB8;
    font-size: 11px;
    font-weight: 500;
    padding: 0;
    text-decoration: none;
}
#sidebarLogoutBtn:hover {
    color: #FF5630;
}
"""

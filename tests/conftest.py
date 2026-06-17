"""Shared pytest configuration.

Force Qt's offscreen platform plugin so widget tests run headlessly (CI has no
display server). Set before any QApplication is created.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

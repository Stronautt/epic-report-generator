"""Epic Report Generator — Jira Epic progress PDF reports."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("epic-report-generator")
except PackageNotFoundError:
    __version__ = "0.0.0"

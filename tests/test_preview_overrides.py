"""Tests for report-generation child resolution (Include / order / rename)."""

from __future__ import annotations

from epic_report_generator.core.data_models import ChildOverride, JiraIssue
from epic_report_generator.ui.preview_panel import _resolve_children


def _issue(key: str, summary: str = "S") -> JiraIssue:
    return JiraIssue(
        key=key,
        summary=summary,
        status="To Do",
        status_category="To Do",
        resolution=None,
        issue_type="Story",
        story_points=None,
        created=None,
        resolved=None,
        assignee=None,
    )


def test_resolve_children_drops_excluded():
    children = [_issue("A"), _issue("B"), _issue("C")]
    out = _resolve_children(children, [], {"B": ChildOverride(include=False)})
    assert [c.key for c in out] == ["A", "C"]


def test_resolve_children_reorders_and_renames():
    children = [_issue("A", "a"), _issue("B", "b")]
    out = _resolve_children(
        children, ["B", "A"], {"A": ChildOverride(display_name="Alpha")}
    )
    assert [c.key for c in out] == ["B", "A"]
    assert {c.key: c.summary for c in out} == {"B": "b", "A": "Alpha"}


def test_resolve_children_noop_without_overrides():
    children = [_issue("A"), _issue("B")]
    out = _resolve_children(children, [], {})
    assert [c.key for c in out] == ["A", "B"]


def test_resolve_children_exclude_wins_over_rename_and_order():
    """An excluded child is dropped even when also renamed and ordered."""
    children = [_issue("A"), _issue("B")]
    out = _resolve_children(
        children,
        ["B", "A"],
        {"A": ChildOverride(display_name="Alpha", include=False)},
    )
    assert [c.key for c in out] == ["B"]

"""Integration tests for FR-13 per-child overrides in report generation.

Drives ``preview_panel._generate_report`` with a fake Jira client and a
monkeypatched ``generate_pdf`` so the ReportData assembled from the overrides
can be inspected without touching Jira or Typst.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from epic_report_generator.core.data_models import (
    ChildOverride,
    EpicData,
    JiraIssue,
    ReportConfig,
    ReportItem,
)
from epic_report_generator.ui import preview_panel

_CREATED = datetime(2024, 1, 1, tzinfo=timezone.utc)
_RESOLVED = datetime(2024, 2, 1, tzinfo=timezone.utc)


def _issue(key: str, *, done: bool = False, sp: float = 1.0) -> JiraIssue:
    return JiraIssue(
        key=key,
        summary=f"summary {key}",
        status="Done" if done else "To Do",
        status_category="Done" if done else "To Do",
        resolution=None,
        issue_type="Story",
        story_points=sp,
        created=_CREATED,
        resolved=_RESOLVED if done else None,
        assignee=None,
    )


def _epic(key: str, children: list[JiraIssue]) -> EpicData:
    return EpicData(
        key=key,
        summary=f"Epic {key}",
        status="In Progress",
        priority=None,
        assignee=None,
        reporter=None,
        created=_CREATED,
        updated=None,
        children=children,
    )


class _FakeJira:
    def __init__(self, by_key=None, by_label=None) -> None:
        self._by_key = by_key or {}
        self._by_label = by_label or {}

    def fetch_report_epics(self, epic_keys, labels, **_kw):
        epics_by_key: dict = {}
        label_to_keys: dict = {}
        for key in epic_keys:
            if key in self._by_key:
                epics_by_key[key] = self._by_key[key]
        for label in labels:
            keys = []
            for epic in self._by_label.get(label, []):
                keys.append(epic.key)
                epics_by_key[epic.key] = epic
            label_to_keys[label] = keys
        return epics_by_key, label_to_keys

    def get_project_name(self, pk):
        return pk

    def fetch_fix_version_dates(self, _pk):
        return {}


@pytest.fixture
def captured(monkeypatch):
    store: dict = {}

    def _fake_generate_pdf(report):
        store["report"] = report
        return b"%PDF-stub"

    monkeypatch.setattr(preview_panel, "generate_pdf", _fake_generate_pdf)
    return store


def _run(jira, item, captured):
    cfg = ReportConfig(items=[item])
    pdf, errors, count = preview_panel._generate_report(jira, cfg, lambda *_a: None)
    assert not errors, errors
    return captured["report"]


def test_epic_consolidated_averages_child_certainty(captured):
    epic = _epic("PROJ-1", [_issue("PROJ-2"), _issue("PROJ-3", done=True)])
    jira = _FakeJira(by_key={"PROJ-1": epic})
    item = ReportItem(
        kind="epic",
        key="PROJ-1",
        scope_certainty=None,
        child_overrides={
            "PROJ-2": ChildOverride("", "Low"),
            "PROJ-3": ChildOverride("Renamed story", "High"),
        },
    )

    report = _run(jira, item, captured)

    # avg(Low, High) → Medium
    assert report.metrics[0].scope_certainty == "Medium"
    # display-name override applied to the child issue
    renamed = {c.key: c.summary for c in report.epics[0].children}
    assert renamed["PROJ-3"] == "Renamed story"
    assert renamed["PROJ-2"] == "summary PROJ-2"  # untouched


def test_label_consolidated_averages_and_renames(captured):
    epic_a = _epic("PROJ-1", [_issue("PROJ-1-1", done=True)])
    epic_b = _epic("PROJ-2", [_issue("PROJ-2-1")])
    jira = _FakeJira(by_label={"team": [epic_a, epic_b]})
    item = ReportItem(
        kind="label",
        key="team",
        display_name="Team",
        scope_certainty=None,
        child_overrides={
            "PROJ-1": ChildOverride("Alpha", "High"),
            "PROJ-2": ChildOverride("", "High"),
        },
    )

    report = _run(jira, item, captured)

    # group certainty = avg(High, High) → High
    assert report.metrics[0].scope_certainty == "High"
    src = report.label_source_epics["team"]
    summaries = {e.key: e.summary for e, _ in src}
    certs = {e.key: em.scope_certainty for e, em in src}
    assert summaries["PROJ-1"] == "Alpha"  # renamed
    assert certs == {"PROJ-1": "High", "PROJ-2": "High"}


def test_parent_certainty_overrides_children(captured):
    epic_a = _epic("PROJ-1", [_issue("PROJ-1-1", done=True)])
    jira = _FakeJira(by_label={"team": [epic_a]})
    item = ReportItem(
        kind="label",
        key="team",
        scope_certainty="Low",  # explicit parent value wins
        child_overrides={"PROJ-1": ChildOverride("", "High")},  # ignored for cert
    )

    report = _run(jira, item, captured)

    assert report.metrics[0].scope_certainty == "Low"
    src = report.label_source_epics["team"]
    assert all(em.scope_certainty == "Low" for _, em in src)


def test_no_overrides_leaves_certainty_unset(captured):
    epic = _epic("PROJ-1", [_issue("PROJ-2")])
    jira = _FakeJira(by_key={"PROJ-1": epic})
    item = ReportItem(kind="epic", key="PROJ-1")

    report = _run(jira, item, captured)

    assert report.metrics[0].scope_certainty is None

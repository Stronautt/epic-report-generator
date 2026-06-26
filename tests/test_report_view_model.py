"""Tests for epic_report_generator.core.report_view_model.

These are pure tests of the view-model: page-descriptor ordering, label-group
expansion, KPI aggregation, None handling, and chart-asset wiring. Metrics are
built without time-series so no trend chart data is produced, except where the
chart geometry is explicitly exercised.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from epic_report_generator.core.data_models import (
    ChildOverride,
    EpicData,
    EpicMetrics,
    HierarchyNode,
    JiraIssue,
    ReportConfig,
    ReportData,
    ReportItem,
)
from epic_report_generator.core.report_view_model import _week_bands, build_report


def _chain() -> list[HierarchyNode]:
    """Custom Epic→Story→Sub-task chain (sub-task hidden) used by hierarchy tests."""
    return [
        HierarchyNode("10000", "Epic", display_tier=0),
        HierarchyNode("10001", "Story", display_tier=1, show=True),
        HierarchyNode("10002", "Sub-task", display_tier=2, show=False),
    ]


def _child(
    key: str,
    *,
    type_id: str = "10001",
    tier: int = 1,
    show: bool = True,
    progress: float = 0.0,
    summary: str = "Child",
) -> JiraIssue:
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
        issue_type_id=type_id,
        display_tier=tier,
        show=show,
        progress=progress,
    )


def _epic(key: str, summary: str = "Summary", children: list[JiraIssue] | None = None) -> EpicData:
    return EpicData(
        key=key,
        summary=summary,
        status="In Progress",
        priority=None,
        assignee=None,
        reporter=None,
        created=None,
        updated=None,
        children=children or [],
    )


def _metrics(progress: float = 50.0, certainty: str | None = None, **kw: object) -> EpicMetrics:
    base: dict[str, object] = dict(
        total_issues=10,
        completed_issues=4,
        open_issues=6,
        unestimated_issues=1,
        total_sp=20.0,
        completed_sp=8.0,
        remaining_sp=12.0,
        progress=progress,
        scope_certainty=certainty,
    )
    base.update(kw)
    return EpicMetrics(**base)  # type: ignore[arg-type]


def _ts_metrics() -> EpicMetrics:
    """Metrics with time-series so an epic chart asset is produced."""
    m = _metrics()
    m.dates = [date(2026, 5, 1), date(2026, 5, 8), date(2026, 5, 15)]
    m.total_sp_over_time = [10.0, 15.0, 20.0]
    m.completed_sp_over_time = [2.0, 5.0, 8.0]
    m.cumulative_issues = [4, 7, 10]
    m.cumulative_unestimated = [2, 1, 1]
    return m


def _epic_report(n: int = 2, **cfg_kw: object) -> ReportData:
    items = []
    epics = []
    metrics = []
    for i in range(n):
        e = _epic(f"E-{i}", f"Epic {i}")
        m = _metrics(progress=float(i * 10), certainty="High" if i == 0 else None)
        items.append((ReportItem("epic", e.key), e, m))
        epics.append(e)
        metrics.append(m)
    cfg = ReportConfig(show_timeline_chart=False, **cfg_kw)  # type: ignore[arg-type]
    return ReportData(
        config=cfg, epics=epics, metrics=metrics, resolved_items=items
    )


def _label_report(expand: bool) -> ReportData:
    e1, e2 = _epic("E-1", "First"), _epic("E-2", "Second")
    m1, m2 = _metrics(progress=80.0, certainty="High"), _metrics(progress=40.0)
    merged = _epic("Backend", "Backend")
    mm = _metrics(progress=60.0, certainty="Medium")
    cfg = ReportConfig(show_timeline_chart=False, expand_label_details=expand)
    return ReportData(
        config=cfg,
        epics=[merged],
        metrics=[mm],
        resolved_items=[(ReportItem("label", "lbl", "Backend", "Medium"), merged, mm)],
        label_source_epics={"lbl": [(e1, m1), (e2, m2)]},
    )


class TestThemePayload:
    def test_default_theme_has_no_overrides(self) -> None:
        theme = build_report(_epic_report())["theme"]
        assert theme["colors"] == {}
        assert theme["font"] == ""

    def test_custom_accent_emits_overrides(self) -> None:
        theme = build_report(_epic_report(report_accent="#16A34A"))["theme"]
        assert theme["colors"]["accent"] == "#16a34a"
        assert "label-header" in theme["colors"]

    def test_invalid_accent_is_ignored(self) -> None:
        theme = build_report(_epic_report(report_accent="not-a-color"))["theme"]
        assert theme["colors"] == {}

    def test_custom_font_threads_through(self) -> None:
        theme = build_report(_epic_report(report_font_family="Roboto"))["theme"]
        assert theme["font"] == "Roboto"


class TestStructure:
    def test_payload_has_expected_top_level_keys(self) -> None:
        payload = build_report(_epic_report())
        assert set(payload) >= {"theme", "title", "footer", "summary", "timeline", "pages"}

    def test_epic_pages_and_rows(self) -> None:
        payload = build_report(_epic_report(n=3))
        assert len(payload["pages"]) == 3
        assert len(payload["summary"]["rows"]) == 3
        assert all(r["kind"] == "epic" for r in payload["summary"]["rows"])

    def test_kpi_strip_aggregates(self) -> None:
        payload = build_report(_epic_report(n=2))
        kpis = {k["label"]: k["value"] for k in payload["summary"]["kpis"]}
        assert kpis["Epics"] == "2"
        assert kpis["Issues"] == "20"  # 2 epics x 10 issues
        assert kpis["Total SP"] == "40"  # 2 x 20.0


class TestLabelExpansion:
    def test_summary_rows_group_then_sources(self) -> None:
        payload = build_report(_label_report(expand=True))
        rows = payload["summary"]["rows"]
        assert rows[0]["kind"] == "group"
        assert rows[0]["label"] == "Backend"
        assert rows[0]["n-epics"] == 2
        assert [r["kind"] for r in rows[1:]] == ["epic", "epic"]

    def test_expanded_pages_have_label_tag(self) -> None:
        payload = build_report(_label_report(expand=True))
        assert len(payload["pages"]) == 2
        assert all(p["label-tag"] == "Backend" for p in payload["pages"])
        assert {p["key"] for p in payload["pages"]} == {"E-1", "E-2"}

    def test_collapsed_label_single_page(self) -> None:
        payload = build_report(_label_report(expand=False))
        # Summary still shows the group + source rows...
        assert len(payload["summary"]["rows"]) == 3
        # ...but only one (merged) detail page, with no label tag.
        assert len(payload["pages"]) == 1
        assert payload["pages"][0]["key"] == "Backend"
        assert payload["pages"][0]["label-tag"] is None

    def test_epics_kpi_counts_source_epics(self) -> None:
        payload = build_report(_label_report(expand=True))
        kpis = {k["label"]: k["value"] for k in payload["summary"]["kpis"]}
        assert kpis["Epics"] == "2"


class TestNoneHandling:
    def test_optional_title_fields_become_none(self) -> None:
        payload = build_report(_epic_report(title="T"))
        assert payload["title"]["project"] is None
        assert payload["title"]["author"] is None
        assert payload["title"]["notice"] is None
        assert payload["footer"]["enabled"] is False

    def test_confidential_sets_notice_and_footer(self) -> None:
        payload = build_report(
            _epic_report(confidential=True, company_name="ACME")
        )
        assert "ACME" in payload["title"]["notice"]
        assert payload["footer"]["enabled"] is True
        assert "ACME" in payload["footer"]["company"]

    def test_additional_metrics_na_for_missing(self) -> None:
        payload = build_report(_epic_report(show_additional_metrics=True))
        additional = payload["pages"][0]["additional"]
        values = {a["label"]: a["value"] for a in additional}
        assert values["Forecast"] == "N/A"
        assert values["Velocity (4wk)"] == "N/A"

    def test_additional_omitted_when_disabled(self) -> None:
        payload = build_report(_epic_report(show_additional_metrics=False))
        assert payload["pages"][0]["additional"] is None

    def test_certainty_flag(self) -> None:
        # E-0 has certainty "High" in _epic_report.
        payload = build_report(_epic_report(n=2))
        assert payload["summary"]["has-certainty"] is True


class TestChartData:
    """Charts are drawn natively, so the payload carries geometry data."""

    def test_trend_chart_data(self) -> None:
        e = _epic("E-1", "Charted")
        m = _ts_metrics()
        report = ReportData(
            config=ReportConfig(show_timeline_chart=False),
            epics=[e],
            metrics=[m],
            resolved_items=[(ReportItem("epic", "E-1"), e, m)],
        )
        chart = build_report(report)["pages"][0]["chart"]
        assert chart is not None
        assert chart["n"] == 3
        assert chart["total-sp"] == [10.0, 15.0, 20.0]
        assert chart["sp-max"] >= 20
        assert chart["iss-max"] >= max(chart["cum-iss"])
        # Time-proportional x-axis: per-point fractions (samples a week apart).
        assert chart["xs"] == [0.0, 0.5, 1.0]
        assert len(chart["x-ticks"]) >= 2
        assert chart["x-ticks"][0]["x"] == 0.0
        assert chart["x-ticks"][-1]["x"] == pytest.approx(1.0)
        assert "bands" in chart  # weekly background bands for the stepped chart

    def test_week_bands_alternate_within_range(self) -> None:
        # 21 daily samples spanning 3 ISO weeks → shade every other week (1 band),
        # each fraction inside [0, 1] with x0 < x1.
        days = [date(2026, 5, 4) + timedelta(days=i) for i in range(21)]
        bands = _week_bands(days)
        assert bands  # at least one shaded week
        for b in bands:
            assert 0.0 <= b["x0"] < b["x1"] <= 1.0
        # too sparse → no bands (chart needs >= 2 points anyway)
        assert _week_bands(days[:1]) == []

    def test_no_chart_without_timeseries(self) -> None:
        # Fewer than two data points -> no trend chart.
        assert build_report(_epic_report(n=1))["pages"][0]["chart"] is None

    def test_timeline_chart_data(self) -> None:
        e = _epic("E-1", "Dated")
        e.start_date = e.timeline_start = date(2026, 5, 1)
        e.due_date = e.timeline_end = date(2026, 6, 1)
        m = _metrics(progress=50.0, certainty="High")
        report = ReportData(
            config=ReportConfig(show_timeline_chart=True),
            epics=[e],
            metrics=[m],
            resolved_items=[(ReportItem("epic", "E-1"), e, m)],
        )
        chart = build_report(report)["timeline"]["chart"]
        assert chart is not None
        assert chart["domain"] > 0
        assert [r["key"] for r in chart["rows"]] == ["E-1"]
        assert chart["rows"][0]["start"] is not None
        assert len(chart["ticks"]) >= 1
        assert len(chart["tiers"]) >= 1


def _custom_epic_report(
    children: list[JiraIssue],
    *,
    overrides: dict[str, ChildOverride] | None = None,
    show_timeline: bool = False,
) -> ReportData:
    """A single-epic report driven by the custom Epic→Story→Sub-task chain."""
    e = _epic("E-1", "Epic One", children=children)
    e.start_date = e.timeline_start = date(2026, 5, 1)
    e.due_date = e.timeline_end = date(2026, 6, 1)
    m = _metrics(progress=50.0)
    item = ReportItem("epic", "E-1", child_overrides=overrides or {})
    cfg = ReportConfig(
        show_timeline_chart=show_timeline, issue_hierarchy=_chain()
    )
    return ReportData(
        config=cfg, epics=[e], metrics=[m], resolved_items=[(item, e, m)]
    )


class TestNestedSummaryRows:
    """Task 5: visible chain children become nested summary rows."""

    def test_default_chain_emits_no_child_rows(self) -> None:
        """An empty chain keeps the summary epic-only (byte-for-byte default)."""
        # Children carry show=True/display_tier=1 as the fetch leaves them, but
        # with no custom chain configured no nested rows are emitted.
        e = _epic("E-1", "Epic", children=[_child("S-1"), _child("S-2")])
        m = _metrics()
        report = ReportData(
            config=ReportConfig(show_timeline_chart=False),
            epics=[e],
            metrics=[m],
            resolved_items=[(ReportItem("epic", "E-1"), e, m)],
        )
        rows = build_report(report)["summary"]["rows"]
        assert [r["kind"] for r in rows] == ["epic"]

    def test_visible_children_become_rows_in_order(self) -> None:
        kids = [
            _child("S-1", progress=100.0, summary="First"),
            _child("S-2", progress=0.0, summary="Second"),
            _child("SUB-1", type_id="10002", tier=2, show=False),  # hidden tier
        ]
        rows = build_report(_custom_epic_report(kids))["summary"]["rows"]
        assert [r["kind"] for r in rows] == ["epic", "child", "child"]
        children = [r for r in rows if r["kind"] == "child"]
        assert [c["key"] for c in children] == ["S-1", "S-2"]  # hidden one dropped
        assert [c["depth"] for c in children] == [1, 1]
        assert children[0]["summary"] == "First"
        assert children[0]["progress"] == 100

    def test_child_certainty_from_override(self) -> None:
        kids = [_child("S-1")]
        overrides = {"S-1": ChildOverride(scope_certainty="High")}
        payload = build_report(_custom_epic_report(kids, overrides=overrides))
        rows = payload["summary"]["rows"]
        child = next(r for r in rows if r["kind"] == "child")
        assert child["certainty"] == "High"
        # A certainty anywhere flips the column-visible flag.
        assert payload["summary"]["has-certainty"] is True

    def test_label_group_nests_children_under_source_epics(self) -> None:
        e1 = _epic("E-1", "First", children=[_child("S-1")])
        e2 = _epic("E-2", "Second", children=[_child("S-2")])
        m1, m2 = _metrics(progress=80.0), _metrics(progress=40.0)
        merged = _epic("Backend", "Backend")
        mm = _metrics(progress=60.0)
        item = ReportItem("label", "lbl", "Backend")
        cfg = ReportConfig(show_timeline_chart=False, issue_hierarchy=_chain())
        report = ReportData(
            config=cfg,
            epics=[merged],
            metrics=[mm],
            resolved_items=[(item, merged, mm)],
            label_source_epics={"lbl": [(e1, m1), (e2, m2)]},
        )
        rows = build_report(report)["summary"]["rows"]
        assert [r["kind"] for r in rows] == [
            "group",
            "epic",
            "child",
            "epic",
            "child",
        ]

    def test_timeline_uses_per_child_show(self) -> None:
        story = _child("S-1", progress=25.0)
        story.timeline_start, story.timeline_end = date(2026, 5, 3), date(2026, 5, 20)
        hidden = _child("SUB-1", type_id="10002", tier=2, show=False)
        hidden.timeline_start, hidden.timeline_end = date(2026, 5, 4), date(2026, 5, 9)
        report = _custom_epic_report([story, hidden], show_timeline=True)
        chart = build_report(report, icons={"10001": b"<svg/>"})["timeline"]["chart"]
        keys = [r["key"] for r in chart["rows"]]
        assert keys == ["E-1", "S-1"]  # hidden sub-task has no bar
        child_row = next(r for r in chart["rows"] if r["child"])
        assert child_row["depth"] == 1
        assert child_row["icon"] == "icons/10001.svg"


class TestIconGuard:
    """Task 5: an icon path is emitted only when the type's bytes are cached."""

    def test_icon_present_only_when_cached(self) -> None:
        kids = [
            _child("S-1", type_id="10001"),  # cached
            _child("S-2", type_id="10009"),  # not cached
        ]
        payload = build_report(
            _custom_epic_report(kids), icons={"10001": b"<svg/>", "10000": b"<svg/>"}
        )
        rows = payload["summary"]["rows"]
        epic_row = next(r for r in rows if r["kind"] == "epic")
        children = {r["key"]: r for r in rows if r["kind"] == "child"}
        assert epic_row["icon"] == "icons/10000.svg"  # chain tier-0 type, cached
        assert children["S-1"]["icon"] == "icons/10001.svg"
        assert children["S-2"]["icon"] == ""  # uncached → empty, never a path

    def test_no_icons_dict_means_no_paths(self) -> None:
        rows = build_report(_custom_epic_report([_child("S-1")]))["summary"]["rows"]
        assert all(r["icon"] == "" for r in rows)

"""Tests for epic_report_generator.core.report_view_model.

These are pure tests of the view-model: page-descriptor ordering, label-group
expansion, KPI aggregation, None handling, and chart-asset wiring. Metrics are
built without time-series so no trend chart data is produced, except where the
chart geometry is explicitly exercised.
"""

from __future__ import annotations

from datetime import date

from epic_report_generator.core.data_models import (
    EpicData,
    EpicMetrics,
    JiraIssue,
    ReportConfig,
    ReportData,
    ReportItem,
)
from epic_report_generator.core.report_view_model import build_report


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
        assert len(chart["x-ticks"]) >= 2

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

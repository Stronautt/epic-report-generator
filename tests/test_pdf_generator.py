"""Tests for epic_report_generator.core.pdf_generator."""

from __future__ import annotations

import io
from datetime import date, datetime, timedelta, timezone

from pypdf import PdfReader

from epic_report_generator.core.data_models import (
    EpicData,
    JiraIssue,
    ReportConfig,
    ReportData,
)
from epic_report_generator.core.metrics import calculate_metrics
from epic_report_generator.core.pdf_generator import generate_pdf


def _make_issue(
    key: str = "T-1",
    status_category: str = "Done",
    sp: float = 3.0,
) -> JiraIssue:
    now = datetime.now(tz=timezone.utc)
    return JiraIssue(
        key=key,
        summary=f"Issue {key}",
        status="Done" if status_category == "Done" else "Open",
        status_category=status_category,
        resolution=None,
        issue_type="Story",
        story_points=sp,
        created=now - timedelta(days=10),
        resolved=now if status_category == "Done" else None,
        assignee="Tester",
    )


def _make_epic(
    key: str = "PROJ-1", children: list[JiraIssue] | None = None
) -> EpicData:
    return EpicData(
        key=key,
        summary="Test Epic for " + key,
        status="In Progress",
        priority="High",
        assignee="Owner",
        reporter="Reporter",
        created=datetime.now(tz=timezone.utc) - timedelta(days=30),
        updated=datetime.now(tz=timezone.utc),
        children=children or [],
    )


def _make_report(
    num_epics: int = 1,
    confidential: bool = False,
    dark: bool = False,
) -> ReportData:
    epics = []
    metrics_list = []
    for i in range(num_epics):
        children = [
            _make_issue(f"T-{i}-1", "Done", 5),
            _make_issue(f"T-{i}-2", "To Do", 3),
        ]
        epic = _make_epic(f"PROJ-{100 + i}", children)
        epics.append(epic)
        metrics_list.append(calculate_metrics(epic))

    cfg = ReportConfig(
        epic_keys=[e.key for e in epics],
        title="Test Report",
        author="Test Author",
        project_display_name="Test Project",
        report_date=date(2024, 6, 15),
        confidential=confidential,
        company_name="ACME Corp" if confidential else "",
        dark_mode=dark,
    )
    return ReportData(config=cfg, epics=epics, metrics=metrics_list)


class TestGeneratePdf:
    """PDF generator should produce valid PDF bytes."""

    def test_returns_valid_pdf(self) -> None:
        pdf = generate_pdf(_make_report())
        assert isinstance(pdf, bytes)
        assert pdf[:5] == b"%PDF-"

    def test_multiple_epics(self) -> None:
        pdf = generate_pdf(_make_report(num_epics=3))
        assert pdf[:5] == b"%PDF-"
        # More epics → more bytes
        single = generate_pdf(_make_report(num_epics=1))
        assert len(pdf) > len(single)

    def test_dark_mode(self) -> None:
        pdf = generate_pdf(_make_report(dark=True))
        assert pdf[:5] == b"%PDF-"

    def test_confidential_notice_adds_content(self) -> None:
        pdf_conf = generate_pdf(_make_report(confidential=True))
        pdf_plain = generate_pdf(_make_report(confidential=False))
        assert pdf_conf[:5] == b"%PDF-"
        # Confidential report has extra notice text → larger PDF
        assert len(pdf_conf) > len(pdf_plain)

    def test_empty_epics(self) -> None:
        """Report with no epics still produces a valid PDF."""
        cfg = ReportConfig(title="Empty Report")
        report = ReportData(config=cfg)
        pdf = generate_pdf(report)
        assert pdf[:5] == b"%PDF-"

    def test_epic_without_children(self) -> None:
        """An epic with no children should not crash PDF generation."""
        epic = _make_epic("PROJ-99", [])
        metrics = calculate_metrics(epic)
        cfg = ReportConfig(epic_keys=["PROJ-99"])
        report = ReportData(config=cfg, epics=[epic], metrics=[metrics])
        pdf = generate_pdf(report)
        assert pdf[:5] == b"%PDF-"


def _page_count(pdf: bytes) -> int:
    return len(PdfReader(io.BytesIO(pdf)).pages)


class TestPageLayout:
    """Page structure: title + summary + (timeline) + one page per epic."""

    def test_page_count(self) -> None:
        # title + summary + timeline (default on) + 2 epic pages
        pdf = generate_pdf(_make_report(num_epics=2))
        assert _page_count(pdf) == 5

    def test_timeline_toggle_changes_page_count(self) -> None:
        report = _make_report(num_epics=2)
        with_timeline = generate_pdf(report)
        report.config.show_timeline_chart = False
        without_timeline = generate_pdf(report)
        assert _page_count(with_timeline) == _page_count(without_timeline) + 1

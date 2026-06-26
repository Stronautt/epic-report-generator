"""Tests for epic_report_generator.core.pdf_generator."""

from __future__ import annotations

import base64
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

    def test_cjk_content_renders(self) -> None:
        """CJK text in the report exercises the conditional Noto CJK font path."""
        report = _make_report()
        report.config.title = "プロジェクト計画 — 项目进度 — 프로젝트"
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

    def test_custom_chain_with_icons_renders(self) -> None:
        """A custom-chain report with cached icons still renders valid PDF bytes.

        The icon SVGs are written into the Typst project and an icon path lands
        on the epic rows; rendering must succeed with the extra payload keys.
        (Visible nested child rows render from Task 6, where the template gains
        the child branch — here the chain's nested tier is hidden.)
        """
        from epic_report_generator.core.data_models import HierarchyNode

        svg = (
            b'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16">'
            b'<rect width="16" height="16"/></svg>'
        )
        child = _make_issue("S-1", "Done", 5)
        child.issue_type_id = "10001"
        child.display_tier = 1
        child.show = False  # hidden tier → no nested rows for the current template
        epic = _make_epic("PROJ-1", [child])
        cfg = ReportConfig(
            epic_keys=["PROJ-1"],
            issue_hierarchy=[
                HierarchyNode("10000", "Epic", display_tier=0),
                HierarchyNode("10001", "Story", display_tier=1, show=False),
            ],
        )
        report = ReportData(
            config=cfg, epics=[epic], metrics=[calculate_metrics(epic)]
        )
        pdf = generate_pdf(report, icons={"10000": svg, "10001": svg})
        assert pdf[:5] == b"%PDF-"


def _page_count(pdf: bytes) -> int:
    return len(PdfReader(io.BytesIO(pdf)).pages)


def _page_texts(pdf: bytes) -> list[str]:
    return [p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages]


_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16">'
    b'<rect width="16" height="16" fill="#36B37E"/></svg>'
)

# A valid 1x1 PNG — Jira serves many issue-type icons as PNG, not SVG.
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1Pe"
    "AAAADElEQVR4nGP4z8AAAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
)


def test_icon_ext_sniffs_format() -> None:
    """icon_ext picks the extension from the bytes, not a fixed .svg."""
    from epic_report_generator.core.typst_renderer import icon_ext

    assert icon_ext(_PNG) == "png"
    assert icon_ext(_SVG) == "svg"
    assert icon_ext(b"\xff\xd8\xff\xe0junk") == "jpg"
    assert icon_ext(b"GIF89a...") == "gif"
    assert icon_ext(b"<?xml version='1.0'?><svg/>") == "svg"
    assert icon_ext(b"") == "svg"


class TestCustomChainRendering:
    """Task 6: visible chain children + issue-type icons render into the PDF.

    These exercise the new template branches (the summary child-row branch, the
    gantt/epic-header icon boxes) by running the native Typst compiler, plus the
    missing-icon guard and a default-chain stability comparison.
    """

    @staticmethod
    def _custom_report() -> ReportData:
        from epic_report_generator.core.data_models import HierarchyNode

        story = _make_issue("S-1", "Done", 5)
        story.issue_type_id, story.display_tier, story.show = "10001", 1, True
        story.progress = 100.0
        sub = _make_issue("SUB-1", "To Do", 2)
        sub.issue_type_id, sub.display_tier, sub.show = "10002", 2, True
        sub.progress = 0.0
        epic = _make_epic("PROJ-1", [story, sub])
        cfg = ReportConfig(
            epic_keys=["PROJ-1"],
            issue_hierarchy=[
                HierarchyNode("10000", "Epic", display_tier=0),
                HierarchyNode("10001", "Story", display_tier=1, show=True),
                HierarchyNode("10002", "Sub-task", display_tier=2, show=True),
            ],
        )
        return ReportData(
            config=cfg, epics=[epic], metrics=[calculate_metrics(epic)]
        )

    def test_visible_children_render_with_icons(self) -> None:
        pdf = generate_pdf(
            self._custom_report(),
            icons={"10000": _SVG, "10001": _SVG, "10002": _SVG},
        )
        assert pdf[:5] == b"%PDF-"
        # The summary nests the visible children, so their keys appear in text.
        text = "\n".join(_page_texts(pdf))
        assert "S-1" in text and "SUB-1" in text

    def test_png_icons_render(self) -> None:
        # Regression: PNG icon bytes were written to a .svg file, so Typst's SVG
        # decoder hard-errored the whole compile. They must now land in a .png
        # file (path + filename agree via icon_ext) and render.
        pdf = generate_pdf(
            self._custom_report(),
            icons={"10000": _PNG, "10001": _PNG, "10002": _PNG},
        )
        assert pdf[:5] == b"%PDF-"
        assert "S-1" in "\n".join(_page_texts(pdf))

    def test_missing_icon_child_renders(self) -> None:
        # A visible child whose type has no cached icon → empty path, no image()
        # call (image() hard-errors on a missing file). Render must still succeed
        # and the nested row must still appear.
        pdf = generate_pdf(self._custom_report(), icons={"10000": _SVG})
        assert pdf[:5] == b"%PDF-"
        assert "S-1" in "\n".join(_page_texts(pdf))

    def test_default_chain_text_unchanged(self) -> None:
        # The child-row / icon branches never fire on the default (no-chain)
        # path, so a default report's rendered text is identical run-to-run.
        r1 = _page_texts(generate_pdf(_make_report(num_epics=2)))
        r2 = _page_texts(generate_pdf(_make_report(num_epics=2)))
        assert r1 == r2


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

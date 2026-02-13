"""Tests for epic_report_generator.core.chart_generator."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from epic_report_generator.core.data_models import EpicMetrics
from epic_report_generator.core.chart_generator import generate_epic_chart


def _make_metrics(days: int = 10) -> EpicMetrics:
    """Build EpicMetrics with *days* of time-series data."""
    start = date.today() - timedelta(days=days)
    dates = [start + timedelta(days=i) for i in range(days)]
    return EpicMetrics(
        total_issues=5,
        completed_issues=3,
        open_issues=2,
        unestimated_issues=1,
        total_sp=20.0,
        completed_sp=12.0,
        remaining_sp=8.0,
        progress=60.0,
        dates=dates,
        total_sp_over_time=[float(i + 10) for i in range(days)],
        completed_sp_over_time=[float(i) for i in range(days)],
        cumulative_issues=list(range(1, days + 1)),
        cumulative_unestimated=[1] * days,
    )


class TestGenerateEpicChart:
    """Chart generator should produce valid PNG bytes or None."""

    def test_returns_png_bytes(self) -> None:
        result = generate_epic_chart(_make_metrics())
        assert result is not None
        assert isinstance(result, bytes)
        # PNG magic bytes
        assert result[:4] == b"\x89PNG"

    def test_returns_none_for_empty_metrics(self) -> None:
        empty = EpicMetrics()
        assert generate_epic_chart(empty) is None

    def test_dark_mode_produces_png(self) -> None:
        result = generate_epic_chart(_make_metrics(), dark=True)
        assert result is not None
        assert result[:4] == b"\x89PNG"

    def test_custom_dpi(self) -> None:
        lo = generate_epic_chart(_make_metrics(), dpi=72)
        hi = generate_epic_chart(_make_metrics(), dpi=200)
        assert lo is not None and hi is not None
        # Higher DPI → more bytes
        assert len(hi) > len(lo)

    def test_single_day_data(self) -> None:
        """Edge case: only one data point."""
        m = EpicMetrics(
            dates=[date.today()],
            total_sp_over_time=[5.0],
            completed_sp_over_time=[2.0],
            cumulative_issues=[1],
            cumulative_unestimated=[0],
        )
        result = generate_epic_chart(m)
        assert result is not None
